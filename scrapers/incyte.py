"""Incyte Corporation scraper — Jibe Apply (iCIMS) JSON API.

The public careers site (careers.incyte.com) is a client-rendered SPA with
no server-rendered job content — the raw HTML never contains a single job
title or ID, which is why Incyte was previously wired up as a "generic"
keyword monitor (can only flag a vague alert, never produce real postings).

The SPA's own search widget calls an undocumented but unauthenticated JSON
API that returns full job data directly — no separate detail fetch needed:

    GET https://careers.incyte.com/api/jobs?page={n}

    Response: {"jobs": [{"data": {...}}, ...], "totalCount": int, ...}
    Pagination is 1-indexed via "page"; each page returns up to 10 jobs.
    Stop once a page comes back empty or we've collected >= totalCount.

Each job's "data" dict already contains a plain-text description (verified:
no HTML tags), plus title, full_location, req_id, posted_date, categories,
and a language code. The same req_id is published once per language variant
(e.g. "en-us" and "fr-fr" are separate entries for the identical posting) —
deduplicated here by slug, preferring "en-us" when both exist.
"""

import logging

from scrapers.base import BaseScraper
from models import Job

logger = logging.getLogger(__name__)

_API_URL = "https://careers.incyte.com/api/jobs"
_PAGE_SIZE = 10
_MAX_PAGES = 30  # safety ceiling — ~126 jobs / 10 per page today


class IncyteScraper(BaseScraper):
    """Scraper for Incyte's Jibe/iCIMS-backed careers site."""

    def __init__(
        self,
        company: str,
        location_terms: list[str] | None = None,
        title_terms: list[str] | None = None,
    ) -> None:
        self.company = company
        self.careers_url = "https://careers.incyte.com/jobs"
        self._location_terms = location_terms or []
        self._title_terms = title_terms or []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        session = self.build_session()
        raw_by_slug: dict[str, dict] = {}
        total_count: int | None = None

        for page in range(1, _MAX_PAGES + 1):
            resp = self._get_with_retry(session, _API_URL, params={"page": page})
            if resp is None:
                logger.error("[%s] Listing failed at page=%d — stopping", self.company, page)
                break
            try:
                data = resp.json()
            except ValueError as exc:
                logger.error("[%s] JSON parse failed (page=%d): %s", self.company, page, exc)
                break

            batch: list[dict] = data.get("jobs", [])
            if not batch:
                break

            total_count = data.get("totalCount", total_count)
            for item in batch:
                raw = item.get("data") or {}
                slug = raw.get("slug")
                if not slug:
                    continue
                # The same req is published once per language; prefer the
                # "en-us" variant when both exist so scoring (English
                # keyword lists) sees it consistently.
                existing = raw_by_slug.get(slug)
                if existing is None or (
                    existing.get("language") != "en-us" and raw.get("language") == "en-us"
                ):
                    raw_by_slug[slug] = raw

            logger.info(
                "[%s] Page %d: %d results (collected %d unique / %s total)",
                self.company, page, len(batch), len(raw_by_slug), total_count,
            )

            if total_count is not None and len(raw_by_slug) >= total_count:
                break
            if len(batch) < _PAGE_SIZE:
                break

        logger.info("[%s] Listing complete: %d unique jobs", self.company, len(raw_by_slug))

        jobs: list[Job] = []
        for raw in raw_by_slug.values():
            title = (raw.get("title") or "").strip()
            location = raw.get("full_location") or raw.get("location_name") or ""
            if not self._passes_prefilter(
                title, location, self._location_terms, self._title_terms
            ):
                continue
            job = self._parse_job(raw)
            if job:
                jobs.append(job)

        logger.info("[%s] %d jobs passed pre-filter", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_job(self, raw: dict) -> Job | None:
        title = (raw.get("title") or "").strip()
        if not title:
            return None

        slug = raw.get("slug") or ""
        language = raw.get("language") or "en-us"
        location = raw.get("full_location") or raw.get("location_name") or "Location not specified"

        categories = raw.get("categories") or []
        department = ", ".join(c.get("name", "") for c in categories if c.get("name"))

        # Mirrors the public job-page URL format (matches links Incyte itself
        # shares, e.g. on LinkedIn), rather than the apply_url field, which
        # routes through an iCIMS login redirect.
        url = f"https://careers.incyte.com/jobs/{slug}?lang={language}" if slug else self.careers_url

        posted_raw = raw.get("posted_date") or ""
        posted = posted_raw[:10] if posted_raw else ""

        return Job(
            title=title,
            company=self.company,
            location=location,
            url=url,
            shortcode=raw.get("req_id") or slug,
            department=department,
            posted_date=posted,
            description=raw.get("description") or "",
        )
