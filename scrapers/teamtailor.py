"""Teamtailor API scraper.

Teamtailor exposes a JSON:API for published job listings.  The API
requires a company-specific token which is the *public* embed token
embedded in every Teamtailor career site — it is read-only and safe
to commit to config.

Finding the token
-----------------
Open the company's Teamtailor career site (e.g. company.teamtailor.com)
in a browser, open DevTools → Network, filter by XHR/Fetch, and look
for requests to api.teamtailor.com.  The Authorization header of those
requests contains the token:  ``Token token=<YOUR_TOKEN>``.

Alternatively, view the page source and search for "Authorization" or
"token".

API
---
  Listing (paginated, 100 per page):
    GET https://api.teamtailor.com/v1/jobs
        ?include=department,locations
        &page[size]=100
        &page[number]=N

  Required headers:
    Authorization: Token token={api_token}
    X-Api-Version: 20210218
    Accept: application/vnd.api+json

  Response (JSON:API format):
    {
      "data": [
        {
          "id": "12345",
          "type": "jobs",
          "attributes": {
            "title": "Patent Attorney",
            "pitch": "Short teaser text",
            "body": "<p>Full HTML description</p>",
            "created-at": "2024-01-15T10:00:00.000Z"
          },
          "relationships": {
            "department": { "data": {"type": "departments", "id": "100"} },
            "locations":  { "data": [{"type": "locations",  "id": "200"}] }
          },
          "links": {
            "careersite-job-url": "https://company.teamtailor.com/jobs/12345-title"
          }
        }
      ],
      "included": [
        {"id": "100", "type": "departments", "attributes": {"name": "Legal"}},
        {"id": "200", "type": "locations",   "attributes": {"city": "Zurich",
                                                             "country-code": "CH"}}
      ],
      "meta": { "record-count": 5, "page-count": 1, "current-page": 1 }
    }

Config example
--------------
  {
      "name": "Company Name",
      "ats": "teamtailor",
      "subdomain": "company-name",  # → https://company-name.teamtailor.com/jobs
      "api_token": "abc123...",     # public embed token from DevTools
  }
"""

import logging

import cache as job_cache
from scrapers.base import BaseScraper
from models import Job

logger = logging.getLogger(__name__)

_API_URL     = "https://api.teamtailor.com/v1/jobs"
_API_VERSION = "20210218"
_PAGE_SIZE   = 100


class TeamtailorScraper(BaseScraper):
    """Scraper for companies using the Teamtailor ATS."""

    def __init__(
        self,
        company: str,
        subdomain: str,
        api_token: str,
        location_terms: list[str] | None = None,
        title_terms: list[str] | None = None,
    ) -> None:
        self.company = company
        self.subdomain = subdomain
        self.api_token = api_token
        self.careers_url = f"https://{subdomain}.teamtailor.com/jobs"
        self._location_terms = location_terms or []
        self._title_terms = title_terms or []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        """Fetch all published jobs from the Teamtailor API."""
        session = self.build_session()
        # Inject auth headers at session level so _get_with_retry inherits them.
        session.headers.update({
            "Authorization": f"Token token={self.api_token}",
            "X-Api-Version": _API_VERSION,
            "Accept": "application/vnd.api+json",
        })

        all_data, all_included = self._fetch_all_pages(session)
        logger.info("[%s] Teamtailor API returned %d jobs", self.company, len(all_data))

        # Build O(1) lookup maps from side-loaded included resources.
        departments = {
            item["id"]: (item.get("attributes") or {}).get("name", "")
            for item in all_included
            if item.get("type") == "departments"
        }
        locations = {
            item["id"]: (item.get("attributes") or {}).get("city", "")
            for item in all_included
            if item.get("type") == "locations"
        }

        jobs: list[Job] = []
        for raw in all_data:
            attrs = raw.get("attributes") or {}
            title = (attrs.get("title") or "").strip()

            # Resolve city from first linked location for pre-filter.
            loc_data = ((raw.get("relationships") or {})
                        .get("locations", {})
                        .get("data", []))
            city = locations.get(loc_data[0]["id"], "") if loc_data else ""

            if not self._passes_prefilter(
                title, city, self._location_terms, self._title_terms
            ):
                continue

            job = self._parse_job(raw, departments, locations)
            if job:
                jobs.append(job)

        logger.info("[%s] %d jobs passed pre-filter", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _fetch_all_pages(
        self, session
    ) -> tuple[list[dict], list[dict]]:
        """Fetch every page of job listings; return aggregated (data, included)."""
        all_data: list[dict] = []
        all_included: list[dict] = []
        page = 1

        while True:
            resp = self._get_with_retry(
                session,
                _API_URL,
                params={
                    "include":       "department,locations",
                    "page[size]":    _PAGE_SIZE,
                    "page[number]":  page,
                },
            )
            if resp is None:
                logger.error(
                    "[%s] Teamtailor: failed to fetch page %d", self.company, page
                )
                break

            try:
                payload = resp.json()
            except ValueError as exc:
                logger.error(
                    "[%s] Teamtailor: JSON parse error on page %d: %s",
                    self.company, page, exc,
                )
                break

            all_data.extend(payload.get("data") or [])
            all_included.extend(payload.get("included") or [])

            page_count = (payload.get("meta") or {}).get("page-count") or 1
            if page >= page_count:
                break
            page += 1

        return all_data, all_included

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_job(
        self,
        raw: dict,
        departments: dict[str, str],
        locations: dict[str, str],
    ) -> Job | None:
        attrs = raw.get("attributes") or {}
        title = (attrs.get("title") or "").strip()
        if not title:
            return None

        rels = raw.get("relationships") or {}

        # Department
        dept_rel = (rels.get("department") or {}).get("data") or {}
        department = departments.get(dept_rel.get("id", ""), "")

        # Location — use first city; fall back to bare "Switzerland"
        loc_data = (rels.get("locations") or {}).get("data") or []
        city = locations.get(loc_data[0]["id"], "") if loc_data else ""
        location = self._ensure_switzerland(city)

        # Public URL: prefer the careersite link supplied by the API
        links = raw.get("links") or {}
        url = (
            links.get("careersite-job-url")
            or f"{self.careers_url}/{raw.get('id', '')}"
        )

        created_at = (attrs.get("created-at") or "")[:10]

        cached = job_cache.get(url)
        if cached:
            description = cached["description"]
        else:
            # "body" is the full HTML description; "pitch" is the short teaser.
            html = attrs.get("body") or attrs.get("pitch") or ""
            description = self._strip_html(html)
            job_cache.put(url, description, url)

        return Job(
            title=title,
            company=self.company,
            location=location,
            url=url,
            department=department,
            posted_date=created_at,
            description=description,
        )
