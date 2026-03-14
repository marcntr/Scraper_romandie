"""Ashby ATS scraper.

Ashby exposes a public, unauthenticated REST API for companies that host
their job board on jobs.ashbyhq.com:

  GET https://api.ashbyhq.com/posting-api/job-board/{slug}

  Returns all published jobs in a single JSON response — no pagination.
  Each job includes the full description HTML, so no Phase 2 detail fetch
  is needed.

  Response structure:
    {
      "jobs": [
        {
          "id":              "uuid",
          "title":           "Implementation Manager",
          "department":      "Customer Experience",
          "team":            "...",
          "employmentType":  "FullTime",
          "location":        "Zurich, Switzerland",   ← clean string
          "publishedAt":     "2026-02-10T23:58:26.288+00:00",
          "isRemote":        true,
          "workplaceType":   "Hybrid",                ← OnSite | Remote | Hybrid
          "address": {
            "postalAddress": {
              "addressCountry":  "Switzerland",
              "addressLocality": "Zurich",
              "addressRegion":   "..."
            }
          },
          "jobUrl":          "https://jobs.ashbyhq.com/{slug}/{id}",
          "descriptionHtml": "<p>...</p>",
          "descriptionPlain": "plain text version"
        }, ...
      ]
    }
"""

import logging

import cache as job_cache
from models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

_API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


class AshbyScraper(BaseScraper):
    """Scraper for any company whose careers site is hosted on Ashby."""

    def __init__(
        self,
        company: str,
        slug: str,
        location_terms: list[str] | None = None,
        title_terms: list[str] | None = None,
    ) -> None:
        self.company = company
        self.slug = slug
        self.careers_url = f"https://jobs.ashbyhq.com/{slug}"
        self._location_terms = location_terms or []
        self._title_terms = title_terms or []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        """Fetch all published jobs from the Ashby job board API."""
        session = self.build_session()
        url = _API_URL.format(slug=self.slug)

        resp = self._get_with_retry(session, url)
        if resp is None:
            logger.error("[%s] Failed to fetch Ashby board — returning empty", self.company)
            return []

        try:
            data = resp.json()
        except ValueError as exc:
            logger.error("[%s] Failed to parse Ashby JSON: %s", self.company, exc)
            return []

        raw_jobs: list[dict] = data.get("jobs", [])
        logger.info("[%s] Ashby API returned %d jobs", self.company, len(raw_jobs))

        jobs: list[Job] = []
        for raw in raw_jobs:
            if not raw.get("isListed", True):
                continue

            title = (raw.get("title") or "").strip()
            location = (raw.get("location") or "").strip()

            # Phase 1.5 pre-filter before HTML stripping
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

        job_url = (raw.get("jobUrl") or "").strip() or self.careers_url
        location = (raw.get("location") or "").strip() or "Location not specified"
        department = (raw.get("department") or "").strip()

        # publishedAt: "2026-02-10T23:58:26.288+00:00" → "2026-02-10"
        published_at = (raw.get("publishedAt") or "")[:10]

        # Description: prefer plain text; fall back to stripping HTML
        description = (raw.get("descriptionPlain") or "").strip()
        if not description:
            description = self._strip_html(raw.get("descriptionHtml") or "")
        else:
            description = description[:8000]

        cached = job_cache.get(job_url)
        if cached:
            description = cached["description"]
        else:
            job_cache.put(job_url, description, job_url)

        return Job(
            title=title,
            company=self.company,
            location=location,
            url=job_url,
            department=department,
            posted_date=published_at,
            description=description,
        )
