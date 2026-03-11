"""Scraper for Alec Allan & Associés SA (Swiss finance/legal recruiter).

Job data source
---------------
Jobs are served via the HR4You platform as a public XML feed:

  GET https://alecallan.hr4you.org/api/jobs/xml/set/website

The XML root element is <HR4YOU_JOBS>; each job is a <job> element.

Relevant child elements
-----------------------
  <jobTitle>          : job title
  <jobRegion>         : Swiss canton abbreviation or region name in German
                        e.g. "Genf" (= Geneva), "Waadt" (= Vaud)
  <jobOffer>          : canonical URL to the job detail page
  <jobPublishingDateFrom> : ISO date "YYYY-MM-DD" when the posting went live

Region normalisation
--------------------
HR4You stores the Swiss region in German.  The _REGION_MAP translates the
values seen in practice to names that the geographic scorer can match
(SCORE_LOCATION_POSITIVE / SCORE_LOCATION_NEUTRAL use lowercase substring
matching).  Unknown region strings are kept as-is with ", Switzerland"
appended so the LOCATION_FILTERS pre-filter always passes.
"""

import logging
import xml.etree.ElementTree as ET

from models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

_XML_URL = "https://alecallan.hr4you.org/api/jobs/xml/set/website"
_CAREERS_URL = "https://www.alecallan.com/our-job-offers/?lang=en"

_REGION_MAP: dict[str, str] = {
    "Genf":    "Geneva, Switzerland",
    "Waadt":   "Vaud, Switzerland",
    "Bern":    "Bern, Switzerland",
    "Basel":   "Basel, Switzerland",
    "Zürich":  "Zürich, Switzerland",
    "Zug":     "Zug, Switzerland",
    "Luzern":  "Luzern, Switzerland",
    "Freiburg": "Fribourg, Switzerland",
    "Wallis":  "Valais, Switzerland",
    "Neuenburg": "Neuchâtel, Switzerland",
    "Jura":    "Jura, Switzerland",
    "Solothurn": "Solothurn, Switzerland",
    "Aargau":  "Aargau, Switzerland",
    "Thurgau": "Thurgau, Switzerland",
    "St. Gallen": "St. Gallen, Switzerland",
    "Graubünden": "Graubünden, Switzerland",
}


class AlecAllanScraper(BaseScraper):
    """Scrapes job listings from Alec Allan via the HR4You XML feed."""

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
        resp = self._get_with_retry(session, _XML_URL)
        if resp is None:
            logger.error("[%s] Failed to fetch HR4You XML feed", self.company)
            return []

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            logger.error("[%s] XML parse error: %s", self.company, exc)
            return []

        jobs: list[Job] = []
        for job_el in root.findall(".//job"):
            job = self._parse_job_element(job_el)
            if job:
                jobs.append(job)

        logger.info("[%s] %d jobs collected", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_job_element(self, job_el: ET.Element) -> Job | None:
        title = (job_el.findtext("jobTitle") or "").strip()
        if not title:
            return None

        url = (job_el.findtext("jobOffer") or "").strip()
        if not url:
            return None

        raw_region = (job_el.findtext("jobRegion") or "").strip()
        location = self._normalise_region(raw_region)

        posted_date = (job_el.findtext("jobPublishingDateFrom") or "").strip()
        # Keep only the date part if datetime is included
        if "T" in posted_date:
            posted_date = posted_date.split("T")[0]

        return Job(
            title=title,
            company=self.company,
            location=location,
            url=url,
            posted_date=posted_date,
        )

    @staticmethod
    def _normalise_region(raw_region: str) -> str:
        """Map a German region name to a scorer-friendly English string."""
        if not raw_region:
            return "Switzerland"
        mapped = _REGION_MAP.get(raw_region)
        if mapped:
            return mapped
        # Unknown region — keep as-is, ensure Switzerland is present
        if "switzerland" not in raw_region.lower():
            return f"{raw_region}, Switzerland"
        return raw_region
