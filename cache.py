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
      ...
    }

Pruning contract:
    ``prune_and_save(active_urls)`` deletes every entry whose
    ``external_url`` is NOT in ``active_urls``.  This ensures that filled or
    removed jobs are evicted from the file, keeping Git history compact.
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


def prune_and_save(active_urls: set[str]) -> None:
    """Remove stale entries and persist the cache to disk.

    An entry is stale if its ``external_url`` is not in *active_urls*
    (meaning the job was filled or removed during this run).

    Args:
        active_urls: Set of public job URLs that appeared in the current run's
                     matched results.
    """
    with _lock:
        before = len(_store)
        _store = {
            k: v for k, v in _store.items()
            if v.get("external_url") in active_urls
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
