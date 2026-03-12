"""Scraper for Michael Page Switzerland (www.michaelpage.ch).

Strategy
--------
Michael Page Switzerland runs a Drupal-based site that server-renders job
listings in paginated HTML at:

    https://www.michaelpage.ch/jobs/switzerland?page=N   (page 0 = first page)

Each page contains ~10–15 job cards.  The site has no structured ATS API;
listing data is parsed directly from the HTML.

Card structure
--------------
Cards do not share a unique CSS class, but each job title is wrapped in an
<h3> containing an <a href="/job-detail/..."> link.  The first <p> sibling
after the <h3> inside the same parent div is the location.

    <div>                                    ← card container (no class)
      <h3>
        <a href="/job-detail/[slug]/ref/[id]">Title</a>
      </h3>
      <p>Location</p>                        ← first <p>
      <p>Permanent</p>                       ← second <p> (contract type)
      <p>Short description…</p>
      …
    </div>

Pagination
----------
Pages are fetched sequentially starting at ?page=0.  Pagination stops when
a page returns zero job cards (empty page = end of results) or MAX_PAGES is
reached as a safety cap.

No descriptions are fetched — the listing snippet is not stored and scoring
operates on title keywords only.  Michael Page covers all industries so the
title pre-filter applied by main.py's apply_filters() provides the necessary
narrowing.
"""

import logging
import time

from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL    = "https://www.michaelpage.ch"
_LIST_URL   = f"{BASE_URL}/jobs/switzerland"
MAX_PAGES   = 25          # safety cap (~375 jobs at ~15 per page)
_PAGE_DELAY = 1.0         # seconds between paginated requests


class MichaelPageScraper(BaseScraper):
    """Scrapes Swiss job listings from Michael Page Switzerland."""

    def __init__(
        self,
        company: str,
        location_terms: list[str],
        title_terms: list[str],
    ) -> None:
        self.company      = company
        self.careers_url  = _LIST_URL
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

        for h3 in soup.find_all("h3"):
            link = h3.find("a", href=lambda h: h and "/job-detail/" in h)
            if not link:
                continue

            title = link.get_text(strip=True)
            if not title:
                continue

            href = link.get("href", "").strip()
            full_url = href if href.startswith("http") else f"{BASE_URL}{href}"

            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Location: first <p> in the card's parent div
            parent   = h3.parent
            paras    = parent.find_all("p") if parent else []
            raw_loc  = paras[0].get_text(strip=True) if paras else ""
            location = raw_loc if raw_loc else "Switzerland"
            if "switzerland" not in location.lower():
                location = f"{location}, Switzerland"

            jobs.append(Job(
                title=title,
                company=self.company,
                location=location,
                url=full_url,
            ))

        return jobs
