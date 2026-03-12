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
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_FILE = Path("seen_jobs.json")

# In-memory store — populated by load(), mutated by put(), read by get().
_store: dict[str, dict] = {}
_lock = threading.Lock()


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
        _store = {}


def get(key: str) -> dict | None:
    """Return the cached entry for *key*, or None if not present."""
    with _lock:
        return _store.get(key)


def put(key: str, description: str, external_url: str) -> None:
    """Store or update an entry."""
    with _lock:
        _store[key] = {"description": description, "external_url": external_url}


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
            if k.startswith("_generic:") or v.get("external_url") in active_urls
        }
        pruned = before - len(_store)
        if pruned:
            logger.info(
                "Cache: pruned %d stale entr%s (%d active remain)",
                pruned, "y" if pruned == 1 else "ies", len(_store),
            )
        try:
            with _CACHE_FILE.open("w", encoding="utf-8") as fh:
                json.dump(_store, fh, indent=2, ensure_ascii=False)
            logger.info("Cache: saved %d entr%s to %s",
                        len(_store), "y" if len(_store) == 1 else "ies", _CACHE_FILE)
        except OSError as exc:
            logger.error("Cache: failed to write %s: %s", _CACHE_FILE, exc)
