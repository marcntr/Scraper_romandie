"""Scraper for Hays Switzerland (www.hays.ch).

Why session-based pagination?
-----------------------------
The site runs on Liferay CMS.  The first page is server-side-rendered; all
further pages require the Liferay session cookies (JSESSIONID, GUEST_LANGUAGE_ID,
COOKIE_SUPPORT, Incapsula cookies) that are set on the initial request.
Without those cookies, paginated requests return empty pages or timeouts.

Strategy
--------
1. Establish a session by fetching the base URL with
   ``?specialism=Life+Sciences`` so all results are life-science related.
2. Paginate using the URL pattern:
     /en/jobsearch/job-offers/s/unknown/Life Sciences/p/{n}/?q=&ij=false
3. Stop when a page returns zero job cards (Swiss jobs are on early pages;
   non-Swiss results dominate from ~page 3 onwards).
4. Limit to MAX_PAGES as a safety cap.

Card structure (.search__result)
----------------------------------
  - Title    : .search__result__header__title  (or <h4>)
  - URL      : a.search__result__link[href]    (relative — prefixed with BASE_URL)
  - Location : second .search__result__job__attribute  (e.g. "Basel Stadt")
               The city name is appended with ", Switzerland" so the
               LOCATION_FILTERS pre-filter always passes.
"""

import logging
import time

from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hays.ch"
_CAREERS_URL = f"{BASE_URL}/en/jobsearch/job-offers"
_START_URL = f"{_CAREERS_URL}?specialism=Life+Sciences"
_PAGE_URL_TPL = f"{BASE_URL}/en/jobsearch/job-offers/s/unknown/Life+Sciences/p/{{n}}/?q=&ij=false"

MAX_PAGES = 3          # Stop after this many pages even if cards are still found
_INTER_PAGE_DELAY = 2  # seconds between paginated requests


class HaysScraper(BaseScraper):
    """Scrapes Swiss life-science job listings from Hays CH."""

    def __init__(
        self,
        company: str,
        location_terms: list[str],
        title_terms: list[str],
    ) -> None:
        self.company = company
        self.careers_url = _CAREERS_URL
        self.location_terms = location_terms
        self.title_terms = title_terms

    # ------------------------------------------------------------------
    # BaseScraper interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        session = self.build_session()
        jobs: list[Job] = []
        seen_urls: set[str] = set()

        # Page 1 — establishes the session cookies
        resp = self._get_with_retry(session, _START_URL)
        if resp is None:
            logger.error("[%s] Failed to fetch initial page", self.company)
            return []

        page1_jobs = self._parse_cards(resp.text, seen_urls)
        jobs.extend(page1_jobs)
        logger.info("[%s] Page 1: %d cards", self.company, len(page1_jobs))

        if not page1_jobs:
            return jobs

        # Pages 2..MAX_PAGES
        for page_num in range(2, MAX_PAGES + 1):
            time.sleep(_INTER_PAGE_DELAY)
            url = _PAGE_URL_TPL.format(n=page_num)
            resp = self._get_with_retry(session, url)
            if resp is None:
                logger.warning("[%s] Page %d fetch failed — stopping", self.company, page_num)
                break

            page_jobs = self._parse_cards(resp.text, seen_urls)
            logger.info("[%s] Page %d: %d cards", self.company, page_num, len(page_jobs))
            if not page_jobs:
                break
            jobs.extend(page_jobs)

        logger.info("[%s] %d total jobs collected", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_cards(self, html: str, seen_urls: set[str]) -> list[Job]:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[Job] = []

        for card in soup.select(".search__result"):
            job = self._parse_card(card, seen_urls)
            if job:
                jobs.append(job)

        return jobs

    def _parse_card(self, card, seen_urls: set[str]) -> Job | None:
        title_el = card.select_one(".search__result__header__title") or card.find("h4")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        if not title:
            return None

        link = card.select_one("a.search__result__link")
        if not link:
            return None
        href = link.get("href", "").strip()
        # Hays occasionally embeds an absolute URL inside another BASE_URL prefix
        if href.startswith(BASE_URL + BASE_URL):
            href = href[len(BASE_URL):]
        full_url = href if href.startswith("http") else f"{BASE_URL}{href}"

        if full_url in seen_urls:
            return None
        seen_urls.add(full_url)

        # Location: second .search__result__job__attribute div
        attrs = card.select(".search__result__job__attribute")
        raw_location = attrs[1].get_text(strip=True) if len(attrs) > 1 else ""

        location = raw_location
        if location and "switzerland" not in location.lower():
            location = f"{location}, Switzerland"
        if not location:
            location = "Switzerland"

        return Job(
            title=title,
            company=self.company,
            location=location,
            url=full_url,
        )
