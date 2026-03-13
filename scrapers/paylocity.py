"""Paylocity ATS scraper.

Fetch strategy (verified via live HTML probe):

Phase 1 — Single GET to the public careers page.
  URL: https://recruiting.paylocity.com/recruiting/jobs/All/{company_guid}/{company_slug}
  All jobs are server-rendered into window.pageData.Jobs — one request, no pagination.
  Fields: JobId, JobTitle, LocationName, PublishedDate, HiringDepartment, IsRemote

Phase 1.5 — In-memory pre-filter on location + title.

Phase 2 — Per-job detail fetch (description only).
  URL: https://recruiting.paylocity.com/Recruiting/Jobs/Details/{JobId}
  Description is in a schema.org JSON-LD <script> block:
    {"@context": "https://schema.org", "@type": "JobPosting", "description": "<html>..."}
  Public URL: same detail URL.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import cache as job_cache
from scrapers.base import BaseScraper
from models import Job

logger = logging.getLogger(__name__)

_BASE          = "https://recruiting.paylocity.com"
_LISTING_URL   = _BASE + "/recruiting/jobs/All/{company_guid}/{company_slug}"
_DETAIL_URL    = _BASE + "/Recruiting/Jobs/Details/{job_id}"

_PHASE2_WORKERS = 4   # concurrent detail fetches


class PaylocityScraper(BaseScraper):
    """Scraper for any company whose careers site is hosted on Paylocity."""

    def __init__(
        self,
        company: str,
        company_guid: str,
        company_slug: str,
        location_terms: list[str] | None = None,
        title_terms: list[str] | None = None,
    ) -> None:
        self.company       = company
        self.company_guid  = company_guid
        self.company_slug  = company_slug
        self._location_terms = location_terms or []
        self._title_terms    = title_terms or []

        self.careers_url = _LISTING_URL.format(
            company_guid=company_guid,
            company_slug=company_slug,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        """Fetch all relevant jobs via the Paylocity HTML embed (2-phase)."""
        session = self.build_session()

        # ── Phase 1: single GET — all jobs are in window.pageData ─────────
        resp = self._get_with_retry(session, self.careers_url)
        if resp is None:
            logger.error("[%s] Could not fetch listing page", self.company)
            return []

        raw_jobs = self._parse_listing(resp.text)
        logger.info("[%s] Phase 1 complete: %d listings collected",
                    self.company, len(raw_jobs))

        if not raw_jobs:
            return []

        # ── Phase 1.5: pre-filter by location + title ─────────────────────
        candidates: list[dict] = []
        for raw in raw_jobs:
            if self._passes_prefilter(
                raw.get("JobTitle") or "",
                raw.get("LocationName") or "",
                self._location_terms,
                self._title_terms,
            ):
                candidates.append(raw)

        logger.info("[%s] Pre-filter: %d / %d listings pass location + title",
                    self.company, len(candidates), len(raw_jobs))

        if not candidates:
            return []

        # ── Phase 2: fetch descriptions concurrently ──────────────────────
        jobs: list[Job] = []
        with ThreadPoolExecutor(max_workers=_PHASE2_WORKERS,
                                thread_name_prefix="paylocity") as pool:
            futures = {
                pool.submit(self._fetch_one, raw): raw
                for raw in candidates
            }
            for future in as_completed(futures):
                try:
                    job = future.result()
                    if job:
                        jobs.append(job)
                except Exception as exc:
                    raw = futures[future]
                    logger.warning("[%s] Detail fetch raised for job %s: %s",
                                   self.company, raw.get("JobId"), exc)

        logger.info("[%s] Phase 2 complete: %d jobs with descriptions",
                    self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Per-job detail fetch (called from thread pool)
    # ------------------------------------------------------------------

    def _fetch_one(self, raw: dict) -> Job | None:
        """Fetch description for a single candidate and return a Job.

        Each thread builds its own session to avoid sharing connection state
        across concurrent requests.  Cache hits skip the network entirely.
        """
        job_id = raw.get("JobId") or ""
        cached = job_cache.get(job_id) if job_id else None
        if cached:
            return self._parse_job(raw, "", description=cached["description"])
        session     = self.build_session()
        detail_html = self._fetch_detail(session, job_id)
        job         = self._parse_job(raw, detail_html)
        if job and job_id:
            job_cache.put(job_id, job.description, job.url)
        return job

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_listing(html: str) -> list[dict]:
        """Extract window.pageData.Jobs from the careers page HTML."""
        m = re.search(r'window\.pageData\s*=\s*(\{.*?\});\s*</script>',
                      html, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []
        return data.get("Jobs") or []

    def _parse_job(
        self,
        raw: dict,
        detail_html: str,
        description: str | None = None,
    ) -> Job | None:
        title = (raw.get("JobTitle") or "").strip()
        if not title:
            return None

        location   = (raw.get("LocationName") or "").strip()
        posted     = (raw.get("PublishedDate") or "")[:10]
        department = (raw.get("HiringDepartment") or "").strip()
        url        = _DETAIL_URL.format(job_id=raw.get("JobId") or "")
        if description is None:
            description = self._extract_description(detail_html)

        return Job(
            title=title,
            company=self.company,
            location=location,
            url=url,
            shortcode=str(raw.get("JobId", "")),
            department=department,
            posted_date=posted,
            description=description,
        )

    @staticmethod
    def _extract_description(html: str) -> str:
        """Pull description from the schema.org JSON-LD block on the detail page."""
        if not html:
            return ""
        # The description lives in a <script> containing @context schema.org
        for script in re.findall(r'<script[^>]*>(\{[^<]+"@context"[^<]+\})</script>',
                                 html, re.DOTALL):
            try:
                data = json.loads(script)
                raw_html = data.get("description") or ""
                if raw_html:
                    return PaylocityScraper._strip_html(raw_html)
            except json.JSONDecodeError:
                continue
        return ""

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _fetch_detail(self, session: requests.Session, job_id) -> str:
        if not job_id:
            return ""
        url  = _DETAIL_URL.format(job_id=job_id)
        resp = self._get_with_retry(session, url)
        if resp is None:
            logger.warning("[%s] Detail fetch failed for job %s", self.company, job_id)
            return ""
        return resp.text
