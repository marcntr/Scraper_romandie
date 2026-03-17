"""Personio Recruiting XML-feed scraper.

Personio exposes a public, unauthenticated XML feed for each company's
career site — no API key required.

Feed URL
--------
  GET https://{subdomain}.jobs.personio.com/xml?language=en

Response structure (root: <workzag-jobs>, one <position> per opening):

  <workzag-jobs>
    <position>
      <id>12345</id>
      <createdAt>2024-01-15T10:00:00+0200</createdAt>
      <name>Patent Attorney</name>
      <department>Intellectual Property</department>
      <office>Zurich</office>
      <employmentType>permanent</employmentType>
      <recruitingCategory>Legal</recruitingCategory>
      <jobDescriptions>
        <jobDescription>
          <name>Your responsibilities</name>
          <value><![CDATA[<p>HTML content…</p>]]></value>
        </jobDescription>
      </jobDescriptions>
    </position>
  </workzag-jobs>

The public job URL is constructed as:
  https://{subdomain}.jobs.personio.com/job/{id}

Config example
--------------
  {
      "name": "Company Name",
      "ats": "personio",
      "subdomain": "company-name",  # from https://company-name.jobs.personio.com
  }
"""

import logging
from xml.etree import ElementTree as ET

import cache as job_cache
from scrapers.base import BaseScraper
from models import Job

logger = logging.getLogger(__name__)


class PersonioScraper(BaseScraper):
    """Scraper for companies using Personio Recruiting."""

    def __init__(
        self,
        company: str,
        subdomain: str,
        location_terms: list[str] | None = None,
        title_terms: list[str] | None = None,
        language: str = "en",
    ) -> None:
        self.company = company
        self.subdomain = subdomain
        self.careers_url = f"https://{subdomain}.jobs.personio.com"
        self._feed_url = f"{self.careers_url}/xml"
        self._language = language
        self._location_terms = location_terms or []
        self._title_terms = title_terms or []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        """Fetch all published jobs from the Personio XML feed."""
        session = self.build_session()
        resp = self._get_with_retry(
            session,
            self._feed_url,
            params={"language": self._language},
        )
        if resp is None:
            logger.error("[%s] Failed to fetch Personio XML feed", self.company)
            return []

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            logger.error("[%s] Failed to parse Personio XML: %s", self.company, exc)
            return []

        positions = root.findall("position")
        logger.info("[%s] Personio XML returned %d positions", self.company, len(positions))

        jobs: list[Job] = []
        for pos in positions:
            title = (pos.findtext("name") or "").strip()
            office = (pos.findtext("office") or "").strip()

            if not self._passes_prefilter(
                title, office, self._location_terms, self._title_terms
            ):
                continue

            job = self._parse_position(pos)
            if job:
                jobs.append(job)

        logger.info("[%s] %d positions passed pre-filter", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_position(self, pos: ET.Element) -> Job | None:
        title = (pos.findtext("name") or "").strip()
        if not title:
            return None

        job_id = (pos.findtext("id") or "").strip()
        office = (pos.findtext("office") or "").strip()
        department = (pos.findtext("department") or "").strip()
        created_at = (pos.findtext("createdAt") or "")[:10]

        location = self._ensure_switzerland(office)
        url = f"{self.careers_url}/job/{job_id}" if job_id else self.careers_url

        cached = job_cache.get(url)
        if cached:
            description = cached["description"]
        else:
            # Concatenate all jobDescription sections into one HTML blob.
            html_parts: list[str] = []
            for jd in pos.findall("jobDescriptions/jobDescription"):
                section_name = (jd.findtext("name") or "").strip()
                section_value = (jd.findtext("value") or "").strip()
                if section_name:
                    html_parts.append(f"<h3>{section_name}</h3>")
                if section_value:
                    html_parts.append(section_value)
            description = self._strip_html("".join(html_parts))
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
