"""Scraper for Randstad Switzerland (life science sector pages).

Why sector pages instead of the main /en/jobs/ listing
-------------------------------------------------------
The main Randstad CH jobs page is a Next.js app that SSR-renders only the
first 30 of ~1 100 jobs; pagination and filtering are handled entirely by
client-side JavaScript.  Hitting /en/jobs/?page=N always returns the same
30 jobs regardless of the parameter.

Instead, we scrape targeted sector pages that are small enough to be fully
server-side rendered in a single request:

  /en/jobs/s-research/
      Natural scientists, chemists, microbiologists, clinical specialists.

  /en/jobs/s-doctors-medical-specialists/s2-medical-pharmaceutical-specialists/
      Pharmacology associates and pharmaceutical specialists.

Jobs are deduplicated by URL across all sector pages.

Page structure (per sector page):
  - Container : li.cards__item
  - Title     : h3.cards__title > a.cards__link  (strip inner <span>)
  - URL       : a.cards__link[href]  (relative — prefixed with BASE_URL)
  - Location  : li[data-testid="location-testId"]  (strip SVG icon children)
                e.g. "Basel, Basel-City"
                     "Fribourg, Fribourg"
                     "Bellinzona, Ticino"
  Location is suffixed with ", Switzerland" when not already present so
  that the LOCATION_FILTERS pre-filter ("switzerland" term) always passes,
  while keeping the actual city for accurate geographic scoring.
"""

import logging

from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.randstad.ch"

_SECTOR_PATHS: list[str] = [
    "/en/jobs/s-research/",
    "/en/jobs/s-doctors-medical-specialists/s2-medical-pharmaceutical-specialists/",
]


class RandstadScraper(BaseScraper):
    """Scrapes life science job listings from Randstad Switzerland sector pages."""

    def __init__(
        self,
        company: str,
        location_terms: list[str],
        title_terms: list[str],
    ) -> None:
        self.company = company
        self.careers_url = f"{BASE_URL}/en/jobs/"
        self.location_terms = location_terms
        self.title_terms = title_terms

    # ------------------------------------------------------------------
    # BaseScraper interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        session = self.build_session()
        seen_urls: set[str] = set()
        jobs: list[Job] = []

        for sector_path in _SECTOR_PATHS:
            sector_url = f"{BASE_URL}{sector_path}"
            resp = self._get_with_retry(session, sector_url)
            if resp is None:
                logger.warning("[%s] Could not fetch %s", self.company, sector_url)
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.select("li.cards__item")
            logger.info(
                "[%s] %s — %d cards found",
                self.company, sector_path, len(cards),
            )

            for li in cards:
                job = self._parse_card(li, seen_urls)
                if job:
                    jobs.append(job)

        logger.info("[%s] %d total jobs collected", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_card(self, li, seen_urls: set[str]) -> Job | None:
        a = li.select_one("h3.cards__title a.cards__link")
        if not a:
            return None

        # Remove the inner <span> (decorative overlay) before reading text
        for span in a.find_all("span"):
            span.decompose()
        title = a.get_text(strip=True)
        if not title:
            return None

        href = a.get("href", "")
        if not href:
            return None
        full_url = f"{BASE_URL}{href}" if href.startswith("/") else href

        if full_url in seen_urls:
            return None
        seen_urls.add(full_url)

        location = self._parse_location(li)

        return Job(
            title=title,
            company=self.company,
            location=location,
            url=full_url,
        )

    @staticmethod
    def _parse_location(li) -> str:
        loc_li = li.select_one("li[data-testid='location-testId']")
        if not loc_li:
            return "Switzerland"

        # Remove SVG icon before reading text
        for svg in loc_li.find_all("svg"):
            svg.decompose()
        for span in loc_li.find_all("span"):
            span.decompose()

        location = loc_li.get_text(strip=True)
        return BaseScraper._ensure_switzerland(location)
