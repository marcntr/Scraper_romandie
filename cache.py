"""Incremental job description cache.

Stores per-job description data keyed by scraper-internal path so that
unchanged jobs are not re-fetched on every run.  The cache is backed by
``seen_jobs.json`` which is committed back to the repository after each run.

Structure of seen_jobs.json:
    {
      "/path/to/job": {
          "description": "plain text stripped from HTML",
          "external_url": "https://..."
      },
      "_generic:CompanyName": {
          "keywords": "biomarker,data science"
      },
      ...
    }

Job entries use scraper-internal paths as keys.
Generic-monitor state entries use the ``_generic:<company>`` prefix and are
never pruned — they persist across runs to enable false-positive suppression.

Pruning contract:
    ``prune_and_save(active_urls)`` deletes every job entry whose
    ``external_url`` is NOT in ``active_urls``.  ``active_urls`` must contain
    ALL URLs observed during the scrape (not just those that passed filters),
    so that jobs which exist but didn't match today are not evicted and
    re-fetched next run.  Generic-monitor entries are always preserved.
"""

import json
import logging
import os
import threading
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_FILE = Path("seen_jobs.json")
_TMP_FILE   = Path("seen_jobs.json.tmp")

# In-memory store — populated by load(), mutated by put(), read by get().
_store: dict[str, dict] = {}
# Reverse index: external_url → cache key — kept in sync with _store so that
# get_status() / set_status() run in O(1) instead of O(N).
_url_to_key: dict[str, str] = {}
_lock = threading.Lock()


def _rebuild_index() -> None:
    """Rebuild _url_to_key from _store.  Caller must hold _lock."""
    global _url_to_key
    _url_to_key = {
        v["external_url"]: k
        for k, v in _store.items()
        if "external_url" in v
    }


def _atomic_write(data: dict) -> None:
    """Serialize *data* to a .tmp file then atomically replace the cache file.

    Using os.replace() guarantees the on-disk file is never in a partial state:
    if the process crashes mid-write, the original seen_jobs.json is untouched
    and only the .tmp file may be left behind.
    """
    _TMP_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(_TMP_FILE, _CACHE_FILE)


def load() -> None:
    """Load cache from seen_jobs.json.  Safe to call if the file doesn't exist."""
    global _store
    if not _CACHE_FILE.exists():
        _store = {}
        logger.info("Cache: no seen_jobs.json found — starting empty")
        return
    try:
        with _CACHE_FILE.open(encoding="utf-8") as fh:
            _store = json.load(fh)
        logger.info("Cache: loaded %d entries from %s", len(_store), _CACHE_FILE)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cache: failed to load %s (%s) — starting empty", _CACHE_FILE, exc)
        # Preserve the corrupt file so data isn't silently destroyed on next save.
        if _CACHE_FILE.exists():
            backup = _CACHE_FILE.with_suffix(".corrupt.json")
            try:
                _CACHE_FILE.rename(backup)
                logger.warning("Cache: corrupt file preserved as %s", backup)
            except OSError as rename_exc:
                logger.warning("Cache: could not rename corrupt file: %s", rename_exc)
        _store = {}
    _rebuild_index()


def known_urls() -> set[str]:
    """Return the set of all public job URLs currently in the cache.

    Call this immediately after ``load()`` and before any scraping begins to
    capture the pre-run baseline.  Any job URL absent from this set is new
    this run and should be highlighted in the dashboard.
    """
    with _lock:
        return {
            v["external_url"]
            for v in _store.values()
            if "external_url" in v
        }


def get(key: str) -> dict | None:
    """Return the cached entry for *key*, or None if not present."""
    with _lock:
        return _store.get(key)


def put(key: str, description: str, external_url: str) -> None:
    """Store or update an entry, preserving existing status and snapshot fields."""
    with _lock:
        existing = _store.get(key, {})
        # Also check _statuses fallback so a status set via the server
        # (when the URL was not yet in the main cache) is not lost.
        fallback_status = _store.get("_statuses", {}).get(external_url, "matched")
        _store[key] = {
            **existing,
            "description":  description,
            "external_url": external_url,
            "status":       existing.get("status", fallback_status),
        }
        _url_to_key[external_url] = key


def update_snapshot(external_url: str, job) -> None:
    """Persist scored job metadata so the Applied archive can reconstruct
    full job cards without re-scraping.

    Called once per matched job after scoring.  Creates a new stub entry
    if none exists yet (e.g. for HTML scrapers that never call put()).
    Never overwrites an existing status value.
    """
    with _lock:
        key = _url_to_key.get(external_url)
        if key is None:
            # HTML scraper — no description cache entry yet; create a stub.
            key = external_url
            _store[key] = {"external_url": external_url, "status": "matched"}
            _url_to_key[external_url] = key
        _store[key].update({
            "title":             job.title,
            "company":           job.company,
            "location":          job.location,
            "posted_date":       job.posted_date,
            "department":        job.department,
            "score":             job.score,
            "matched_keywords":  sorted(job.matched_keywords),
            "deducted_keywords": sorted(job.deducted_keywords),
        })


def get_applied_archive() -> list:
    """Return Job objects for every 'applied' cache entry that has a snapshot.

    Used by main.py to populate the Applied tab with archived jobs that are
    no longer live on the web.  Entries without a ``title`` field are stubs
    (status was set before a snapshot was taken) and are skipped.
    """
    from models import Job  # local import — avoids circular dependency at module level
    jobs: list[Job] = []
    with _lock:
        for v in _store.values():
            if v.get("status") != "applied" or not v.get("title"):
                continue
            j = Job(
                title=v.get("title", ""),
                company=v.get("company", ""),
                location=v.get("location", ""),
                url=v.get("external_url", ""),
                posted_date=v.get("posted_date", ""),
                department=v.get("department", ""),
                description=v.get("description", ""),
                score=v.get("score", 0),
                status="applied",
            )
            j.matched_keywords  = set(v.get("matched_keywords",  []))
            j.deducted_keywords = set(v.get("deducted_keywords", []))
            jobs.append(j)
    return jobs


FACET_TTL_DAYS = 7
_FACET_TTL_DAYS = FACET_TTL_DAYS  # backwards-compat alias


def get_facets(tenant: str, portal: str) -> dict | None:
    """Return cached facet data for a Workday tenant/portal if still fresh.

    Returns the full cache entry dict (keys: ``facets``, ``search_texts``,
    ``cached_at``) when the entry exists and is ≤ _FACET_TTL_DAYS old.
    Returns ``None`` if absent or expired so the caller knows to re-probe.
    """
    key = f"_facets:{tenant}:{portal}"
    with _lock:
        entry = _store.get(key)
        if not entry:
            return None
        try:
            age = (date.today() - date.fromisoformat(entry.get("cached_at", ""))).days
        except (ValueError, TypeError):
            return None
        return entry if age <= _FACET_TTL_DAYS else None


def put_facets(tenant: str, portal: str, facets: dict, search_texts: list[str]) -> None:
    """Persist facet discovery results for a Workday tenant/portal."""
    key = f"_facets:{tenant}:{portal}"
    with _lock:
        _store[key] = {
            "facets":       facets,
            "search_texts": search_texts,
            "cached_at":    date.today().isoformat(),
        }


def get_generic_alert(company: str) -> str | None:
    """Return the last-seen keyword string for a GenericMonitor company,
    or None if this company has never triggered an alert."""
    with _lock:
        entry = _store.get(f"_generic:{company}")
        return entry.get("keywords") if entry else None


def put_generic_alert(company: str, keywords_str: str) -> None:
    """Persist the matched keyword string for a GenericMonitor company."""
    with _lock:
        _store[f"_generic:{company}"] = {"keywords": keywords_str}


def get_status(external_url: str) -> str:
    """Return the triage status for a job, defaulting to 'matched'.

    O(1) via the _url_to_key reverse index.
    """
    with _lock:
        key = _url_to_key.get(external_url)
        if key:
            return _store.get(key, {}).get("status", "matched")
        # Fallback: check the _statuses dict (used by generic monitor jobs)
        return _store.get("_statuses", {}).get(external_url, "matched")


def set_status(external_url: str, status: str) -> None:
    """Update the triage status for a job identified by its public URL.

    O(1) via the _url_to_key reverse index.
    """
    with _lock:
        key = _url_to_key.get(external_url)
        if key:
            _store[key]["status"] = status
        else:
            # URL not in main cache (e.g. generic monitor job)
            if "_statuses" not in _store:
                _store["_statuses"] = {}
            _store["_statuses"][external_url] = status


def save() -> None:
    """Persist the current in-memory cache to disk without pruning."""
    with _lock:
        try:
            _atomic_write(_store)
            logger.info("Cache: saved to %s", _CACHE_FILE)
        except OSError as exc:
            logger.error("Cache: failed to write %s: %s", _CACHE_FILE, exc)


def prune_and_save(active_urls: set[str]) -> None:
    """Remove stale job entries and persist the cache to disk.

    A job entry is stale if its ``external_url`` is not in *active_urls*.
    *active_urls* should contain every URL seen during the scrape run,
    regardless of whether the job passed filters — this prevents re-fetching
    descriptions for jobs that exist but didn't match today's criteria.

    Generic-monitor entries (keys prefixed with ``_generic:``) are always
    preserved.

    Args:
        active_urls: Set of all public job URLs observed in the current run.
    """
    global _store
    with _lock:
        before = len(_store)
        _store = {
            k: v for k, v in _store.items()
            if k.startswith("_")
            or v.get("external_url") in active_urls
            or v.get("status") == "applied"   # applied entries are immortal
        }
        pruned = before - len(_store)
        if pruned:
            logger.info(
                "Cache: pruned %d stale entr%s (%d active remain)",
                pruned, "y" if pruned == 1 else "ies", len(_store),
            )
        _rebuild_index()
        try:
            _atomic_write(_store)
            logger.info("Cache: saved %d entr%s to %s",
                        len(_store), "y" if len(_store) == 1 else "ies", _CACHE_FILE)
        except OSError as exc:
            logger.error("Cache: failed to write %s: %s", _CACHE_FILE, exc)
