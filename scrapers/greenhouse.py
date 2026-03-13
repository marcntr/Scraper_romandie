"""Greenhouse ATS scraper.

Greenhouse exposes an unauthenticated public JSON API for companies that
host their job board on boards.greenhouse.io.

Single-call strategy
--------------------
  GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true

  Returns every published job in one response — no pagination needed for
  typical company boards.  Each job object includes:
    - id, title, updated_at, absolute_url
    - location.name
    - departments[].name
    - content (HTML job description, only present when content=true)

Phase 1.5 pre-filter
--------------------
  Location and title checks are applied to the raw listing data *before*
  HTML stripping so that description parsing is skipped for irrelevant jobs.
"""

import logging

import requests

import cache as job_cache
from scrapers.base import BaseScraper
from models import Job

logger = logging.getLogger(__name__)

_API_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


class GreenhouseScraper(BaseScraper):
    """Scraper for any company whose board is hosted on Greenhouse."""

    def __init__(
        self,
        company: str,
        board_token: str,
        location_terms: list[str] | None = None,
        title_terms: list[str] | None = None,
    ) -> None:
        self.company = company
        self.board_token = board_token
        self.careers_url = f"https://boards.greenhouse.io/{board_token}"
        self._location_terms = location_terms or []
        self._title_terms = title_terms or []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        """Fetch all published jobs from the Greenhouse board API."""
        session = self.build_session()
        url = _API_URL.format(token=self.board_token)

        resp = self._get_with_retry(session, url, params={"content": "true"})
        if resp is None:
            logger.error("[%s] Failed to fetch Greenhouse board — returning empty", self.company)
            return []

        try:
            data = resp.json()
        except ValueError as exc:
            logger.error("[%s] Failed to parse Greenhouse JSON: %s", self.company, exc)
            return []

        raw_jobs: list[dict] = data.get("jobs", [])
        logger.info("[%s] Greenhouse API returned %d jobs", self.company, len(raw_jobs))

        jobs: list[Job] = []
        for raw in raw_jobs:
            # Phase 1.5 pre-filter: skip location/title mismatches before
            # stripping HTML (which is the expensive step).
            title = (raw.get("title") or "").strip()
            location_name = (raw.get("location") or {}).get("name") or ""

            if not self._passes_prefilter(
                title, location_name, self._location_terms, self._title_terms
            ):
                continue

            job = self._parse_job(raw)
            if job:
                jobs.append(job)

        logger.info("[%s] %d jobs passed pre-filter", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_job(self, raw: dict) -> Job | None:
        title = (raw.get("title") or "").strip()
        if not title:
            return None

        location_name = (raw.get("location") or {}).get("name") or "Location not specified"

        depts = raw.get("departments") or []
        department = ", ".join(d.get("name", "") for d in depts if d.get("name"))

        url = raw.get("absolute_url") or self.careers_url
        posted = (raw.get("updated_at") or "")[:10]  # ISO date prefix

        cached = job_cache.get(url)
        if cached:
            description = cached["description"]
        else:
            content_html = raw.get("content") or ""
            description = self._strip_html(content_html)
            job_cache.put(url, description, url)

        return Job(
            title=title,
            company=self.company,
            location=location_name,
            url=url,
            department=department,
            posted_date=posted,
            description=description,
        )
