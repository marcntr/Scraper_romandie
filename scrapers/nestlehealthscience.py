"""Scraper for Nestlé Health Science jobs (www.nestlejobs.com/nestle-health-science).

Site structure
--------------
nestlejobs.com is a Drupal/Avature-based portal that server-renders job
listings for individual Nestlé brands.  The Nestlé Health Science section is
at:

    https://www.nestlejobs.com/nestle-health-science?page=N

Each page contains a list of anchor tags linking to jobdetails.nestle.com.
No structured ATS API or XML feed is available (sitemal.xml returns 404).

Card HTML (within each job anchor):
    <a href="https://jobdetails.nestle.com/job/{City}-{Title}/{ID}/?feedId=…">
      <div class="company-name">Nestlé Health Science</div>
      <div class="job-title">Senior Scientist, Biomarker Research</div>
      <div class="location">Vevey, VD — Salaried and Full-time</div>
    </a>

The location field uses the pattern "{City}, {State/Region} — {Employment type}".
Swiss jobs use Swiss canton codes (e.g. "VD" for Vaud, "GE" for Geneva).
Location is extracted from the text before " — " and passed as-is;
apply_filters() in main.py handles the Switzerland pre-filter.

Pagination
----------
Pages are fetched sequentially via ?page=N (0-indexed).  Stops when a page
returns zero job cards.  MAX_PAGES is a safety cap.

Note: Swiss Nestlé Health Science openings may be sparse or zero at any
given time.  The scraper will silently return an empty list in that case.
"""

import logging
import time

from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL      = "https://www.nestlejobs.com"
_BRAND_PATH   = "/nestle-health-science"
_LIST_URL     = f"{BASE_URL}{_BRAND_PATH}"

MAX_PAGES     = 15       # safety cap — brand pages are rarely > 5–6 pages
_PAGE_DELAY   = 1.0      # seconds between paginated requests


class NestleHealthScienceScraper(BaseScraper):
    """Scrapes job listings for Nestlé Health Science from nestlejobs.com."""

    def __init__(
        self,
        company: str,
        location_terms: list[str],
        title_terms: list[str],
    ) -> None:
        self.company        = company
        self.careers_url    = _LIST_URL
        self.location_terms = location_terms
        self.title_terms    = title_terms

    # ------------------------------------------------------------------
    # BaseScraper interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        session   = self.build_session()
        jobs: list[Job]      = []
        seen_urls: set[str]  = set()

        for page in range(MAX_PAGES + 1):
            url = _LIST_URL if page == 0 else f"{_LIST_URL}?page={page}"
            if page > 0:
                time.sleep(_PAGE_DELAY)

            resp = self._get_with_retry(session, url)
            if resp is None:
                logger.warning("[%s] Page %d fetch failed — stopping", self.company, page)
                break

            page_jobs = self._parse_page(resp.text, seen_urls)
            logger.info("[%s] Page %d: %d cards", self.company, page, len(page_jobs))
            if not page_jobs:
                break
            jobs.extend(page_jobs)

        logger.info("[%s] %d total jobs collected", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_page(self, html: str, seen_urls: set[str]) -> list[Job]:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[Job] = []

        for a in soup.find_all("a", href=lambda h: h and "jobdetails.nestle.com/job/" in h):
            href = a.get("href", "").strip()
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            title_el = a.find(class_="job-title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title:
                continue

            location = self._parse_location(a)

            jobs.append(Job(
                title=title,
                company=self.company,
                location=location,
                url=href,
            ))

        return jobs

    @staticmethod
    def _parse_location(anchor) -> str:
        """Extract location from the card's .location div.

        Format: "City, Region — Employment type"
        We keep only the part before " — " to drop the employment-type suffix.
        Switzerland is appended if not already present.
        """
        loc_el = anchor.find(class_="location")
        if not loc_el:
            return "Switzerland"

        raw = loc_el.get_text(strip=True)
        # Strip employment-type suffix (e.g. " — Salaried and Full-time")
        location = raw.split(" — ")[0].strip() if " — " in raw else raw.strip()

        if not location:
            return "Switzerland"
        if "switzerland" not in location.lower():
            location = f"{location}, Switzerland"
        return location
