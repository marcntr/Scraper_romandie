"""Scraper for Gloor & Lang (Swiss life science recruiter).

Page structure (static HTML, no pagination):
  - Container : div.job
  - Title     : <a title="..."> attribute (or h2 text as fallback)
  - URL       : <a href="..."> (external link to starhunter.software)
  - Location  : <p class="industries"> text, format:
                  "Industry: X | Region: Y | Field: Z"
                Region value mapped to a "City/Region, Switzerland" string
                so both the location pre-filter and geographic scorer work.
"""

import logging
import re

from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Map Gloor & Lang's abbreviated / compound region labels to names
# that the geographic scorer can match (SCORE_LOCATION_NEUTRAL /
# SCORE_LOCATION_POSITIVE use lowercase substring matching).
_REGION_MAP: dict[str, str] = {
    "ZG":                 "Zug",
    "ZH":                 "Zürich",
    "ZG - ZH":            "Zug - Zürich",
    "Zürich Nord":        "Zürich Nord",
    "Zürich Süd":         "Zürich Süd",
    "Basel Region":       "Basel",
    "Basel-Aargau":       "Basel-Aargau",
    "Chur Region":        "Chur, Switzerland",
    "Luzern Region":      "Luzern, Switzerland",
    "Winterthur Region":  "Winterthur, Switzerland",
}


class GloorLangScraper(BaseScraper):
    """Scrapes all open positions from the Gloor & Lang jobs page."""

    def __init__(
        self,
        company: str,
        location_terms: list[str],
        title_terms: list[str],
    ) -> None:
        self.company = company
        self.careers_url = "https://www.gloorlang.com/en/job-opportunities/"
        self.location_terms = location_terms
        self.title_terms = title_terms

    # ------------------------------------------------------------------
    # BaseScraper interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        session = self.build_session()
        resp = self._get_with_retry(session, self.careers_url)
        if resp is None:
            logger.error("[%s] Failed to fetch careers page", self.company)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        job_divs = soup.select("div.job")
        logger.info("[%s] Found %d job listings", self.company, len(job_divs))

        jobs: list[Job] = []
        for div in job_divs:
            a = div.find("a", href=True)
            if not a:
                continue

            title = (a.get("title") or "").strip()
            if not title:
                h2 = a.find("h2")
                title = h2.get_text(strip=True) if h2 else a.get_text(strip=True)
            if not title:
                continue

            url = a["href"].strip()

            location = self._parse_location(div)

            jobs.append(Job(
                title=title,
                company=self.company,
                location=location,
                url=url,
            ))

        logger.info("[%s] %d jobs collected", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_location(self, div) -> str:
        """Extract region from the industries paragraph and normalise it."""
        industries_p = div.find("p", class_="industries")
        if not industries_p:
            return "Switzerland"

        text = industries_p.get_text()
        m = re.search(r"Region:\s*([^|]+)", text)
        if not m:
            return "Switzerland"

        raw_region = m.group(1).strip()
        region = _REGION_MAP.get(raw_region, raw_region)

        # Ensure "switzerland" substring is present so LOCATION_FILTERS passes
        if "switzerland" not in region.lower():
            region = f"{region}, Switzerland"

        return region
