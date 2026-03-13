"""SAP SuccessFactors ATS scraper.

SuccessFactors exposes an intentionally obscure but public RSS 1.0 feed:
  GET {careers_url}/sitemal.xml

No authentication is required.  The feed returns all published jobs in a
single response as RSS 1.0 items.

Feed structure (per <item>) — confirmed via live inspection:
  <title>       — "Job Title (City, Country, Region)"
                  Location is the parenthetical suffix, NOT dc:subject
                  (dc:subject is always empty in this feed)
  <link>        — direct apply URL
  <description> — HTML job description, HTML-entity-escaped once
                  (i.e. &lt;p&gt; → must be html.unescape()'d before parsing)

Location extraction
-------------------
  Regex strips the trailing "(City, Country, Region)" from the title.
  The parenthetical portion is used for location matching; the clean
  title (without location) is stored on the Job.

Description decoding
--------------------
  The raw text from ET.findtext("description") is HTML-entity-escaped.
  One pass of html.unescape() converts it to real HTML before BeautifulSoup.

Phase 1.5 pre-filter
--------------------
  Location and title checks are applied to raw RSS data *before* HTML
  stripping to avoid unnecessary BeautifulSoup work for off-target jobs.
"""

import html as html_module
import logging
import re
import xml.etree.ElementTree as ET

import cache as job_cache
from scrapers.base import BaseScraper
from models import Job

logger = logging.getLogger(__name__)

# Matches the trailing "(City, Country, Region)" location tag in BI titles
_LOCATION_SUFFIX_RE = re.compile(r"\s*\(([^)]+)\)\s*$")


class SuccessFactorsScraper(BaseScraper):
    """Scraper for SuccessFactors-hosted careers sites via their public XML feed."""

    def __init__(
        self,
        company: str,
        careers_url: str,
        location_terms: list[str] | None = None,
        title_terms: list[str] | None = None,
    ) -> None:
        self.company = company
        self.careers_url = careers_url.rstrip("/")
        self._location_terms = location_terms or []
        self._title_terms = title_terms or []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        """Fetch all jobs from the SuccessFactors RSS feed."""
        feed_url = f"{self.careers_url}/sitemal.xml"
        session = self.build_session()

        resp = self._get_with_retry(session, feed_url)
        if resp is None:
            logger.error("[%s] Failed to fetch SuccessFactors feed — returning empty", self.company)
            return []

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            logger.error("[%s] Failed to parse XML feed: %s", self.company, exc)
            return []

        items = root.findall(".//item")
        logger.info("[%s] SuccessFactors feed returned %d items", self.company, len(items))

        jobs: list[Job] = []
        for item in items:
            raw_title = (item.findtext("title") or "").strip()

            # Extract location from the parenthetical suffix of the title,
            # and strip it to get the clean job title.
            m = _LOCATION_SUFFIX_RE.search(raw_title)
            if m:
                location = m.group(1).strip()
                clean_title = raw_title[: m.start()].strip()
            else:
                location = ""
                clean_title = raw_title

            # Phase 1.5 pre-filter before HTML stripping
            if not self._passes_prefilter(
                clean_title, location, self._location_terms, self._title_terms
            ):
                continue

            job = self._parse_item(item, clean_title, location)
            if job:
                jobs.append(job)

        logger.info("[%s] %d jobs passed pre-filter", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_item(self, item: ET.Element, title: str, location: str) -> Job | None:
        if not title:
            return None

        url = (item.findtext("link") or "").strip() or self.careers_url

        cached = job_cache.get(url)
        if cached:
            description = cached["description"]
        else:
            # Description is HTML-entity-escaped once by the feed; unescape before parsing.
            raw_desc = item.findtext("description") or ""
            description = self._strip_html(html_module.unescape(raw_desc))
            job_cache.put(url, description, url)

        return Job(
            title=title,
            company=self.company,
            location=location or "Location not specified",
            url=url,
            description=description,
        )
