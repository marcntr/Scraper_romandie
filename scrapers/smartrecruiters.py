"""Generic scraper for companies using the SmartRecruiters public API.

API overview
------------
SmartRecruiters exposes a public, unauthenticated REST API for job postings:

  Listing:
    GET https://api.smartrecruiters.com/v1/companies/{company_id}/postings
        ?country=ch        ← ISO-3166-1 alpha-2 code; filters to Swiss jobs
        &limit=100         ← max results per page

  Response JSON:
    {
      "totalFound": N,
      "content": [
        {
          "id":            "3743990012108856",
          "name":          "Clinical Specialist Strategic Partnerships",
          "releasedDate":  "2026-03-12T07:00:00.000Z",
          "location":      {"city": "Cham", "country": "CH", "region": "ZG",
                            "regionCode": "ZG",
                            "address": "Cham, Zug, Switzerland"},
          "function":      {"id": "...", "label": "Medical Affairs"},
          "ref":           "https://api.smartrecruiters.com/v1/companies/AbbVie/postings/..."
        }, …
      ]
    }

  Individual posting:
    GET {ref}                 ← same URL as the listing's "ref" field

  Response adds:
    "applyUrl":   "https://jobs.smartrecruiters.com/AbbVie/3743990012108856-..."
    "postingUrl": same as applyUrl
    "jobAd":      {
      "sections": {
        "jobDescription": {"text": "<p>HTML description…</p>"}
      }
    }

Strategy
--------
Phase 1 — Listing: fetch all Swiss jobs in one call (country=ch&limit=100).
Phase 2 — Detail: for each listing, fetch the individual posting to obtain
  the public applyUrl and the full job description.  Results are cached by
  the posting's API ref URL to avoid repeated fetches.
Phase 2 is parallelised across DETAIL_WORKERS threads.

Note: SmartRecruiters does not paginate the country-filtered listing in
practice — Swiss jobs are typically ≤ 20, well within the limit=100 cap.
The limit parameter is present as a safeguard.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import cache as job_cache
from models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

_API_BASE     = "https://api.smartrecruiters.com/v1/companies"
DETAIL_WORKERS = 4


class SmartRecruitersScraper(BaseScraper):
    """Scrapes Swiss job listings for a company hosted on SmartRecruiters.

    Parameters
    ----------
    company_id : str
        The SmartRecruiters company identifier (case-sensitive slug, e.g.
        "AbbVie").  Found in the career page's ``CAREERPAGE.companyIdentifier``
        JS variable or at ``careers.smartrecruiters.com/{company_id}``.
    """

    def __init__(
        self,
        company: str,
        company_id: str,
        location_terms: list[str],
        title_terms: list[str],
    ) -> None:
        self.company       = company
        self.company_id    = company_id
        self.careers_url   = f"https://careers.smartrecruiters.com/{company_id}"
        self.location_terms = location_terms
        self.title_terms    = title_terms
        self._listing_url  = f"{_API_BASE}/{company_id}/postings"

    # ------------------------------------------------------------------
    # BaseScraper interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        session = self.build_session()

        # Phase 1: fetch Swiss listing
        listing = self._fetch_listing(session)
        if not listing:
            return []
        logger.info("[%s] %d Swiss posting(s) found", self.company, len(listing))

        # Phase 2: fetch details in parallel (skipping cached entries)
        jobs: list[Job] = []
        to_fetch = []
        for item in listing:
            ref = item.get("ref", "")
            cached = job_cache.get(ref) if ref else None
            if cached:
                jobs.append(self._job_from_listing(item, cached["external_url"],
                                                   cached.get("description", "")))
            else:
                to_fetch.append(item)

        if to_fetch:
            with ThreadPoolExecutor(max_workers=DETAIL_WORKERS,
                                    thread_name_prefix="sr_detail") as pool:
                futures = {pool.submit(self._fetch_detail, session, item): item
                           for item in to_fetch}
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        jobs.append(result)

        logger.info("[%s] %d jobs collected", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fetch_listing(self, session) -> list[dict]:
        params = {"country": "ch", "limit": 100}
        resp = self._get_with_retry(session, self._listing_url, params=params)
        if resp is None:
            logger.error("[%s] Listing request failed", self.company)
            return []
        try:
            data = resp.json()
            return data.get("content", [])
        except ValueError as exc:
            logger.error("[%s] Listing JSON parse error: %s", self.company, exc)
            return []

    def _fetch_detail(self, session, item: dict) -> Job | None:
        ref = item.get("ref", "")
        if not ref:
            return self._job_from_listing(item, "", "")

        resp = self._get_with_retry(session, ref)
        if resp is None:
            logger.warning("[%s] Detail fetch failed for %s", self.company, ref)
            return self._job_from_listing(item, "", "")

        try:
            detail = resp.json()
        except ValueError:
            return self._job_from_listing(item, "", "")

        apply_url   = detail.get("applyUrl") or detail.get("postingUrl") or ""
        description = ""
        job_ad = detail.get("jobAd") or {}
        sections = job_ad.get("sections") or {}
        job_desc_section = sections.get("jobDescription") or {}
        raw_html = job_desc_section.get("text") or ""
        if raw_html:
            description = self._strip_html(raw_html)

        if apply_url and ref:
            job_cache.put(ref, description, apply_url)

        return self._job_from_listing(item, apply_url, description)

    def _job_from_listing(self, item: dict, url: str, description: str) -> Job:
        title    = item.get("name", "").strip()
        loc_obj  = item.get("location") or {}
        city     = loc_obj.get("city") or ""
        address  = loc_obj.get("address") or ""
        location = address if address else (f"{city}, Switzerland" if city else "Switzerland")
        if "switzerland" not in location.lower():
            location = f"{location}, Switzerland"

        # ISO date: "2026-03-12T07:00:00.000Z" → "2026-03-12"
        raw_date = item.get("releasedDate") or ""
        posted_date = raw_date[:10] if raw_date else ""

        dept = (item.get("function") or {}).get("label") or ""

        # Fall back to listing API ref as URL if detail fetch didn't return one
        if not url:
            url = item.get("ref") or self.careers_url

        return Job(
            title=title,
            company=self.company,
            location=location,
            url=url,
            description=description,
            posted_date=posted_date,
            department=dept,
        )
