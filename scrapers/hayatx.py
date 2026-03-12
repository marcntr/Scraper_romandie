"""Scraper for HAYA Therapeutics (www.hayatx.com/careers/).

Strategy
--------
HAYA's careers page is a WordPress site that loads job listings dynamically
via an AJAX action.  The static HTML contains an empty container; jobs are
injected after a POST call to:

    POST https://www.hayatx.com/wp-admin/admin-ajax.php

Required POST parameters:
    action          = "load_jobs_filter"
    filter          = "all"          (location slug; "all" returns everything)
    limit           = 100            (generous cap — HAYA is a small company)
    offset          = 0
    nonce           = <dynamic>      (WordPress nonce, changes on every page load)
    theme           = "dark"
    animated_border = "0"
    fixed_height    = "0"
    gallery         = "0"

Nonce extraction
----------------
The nonce is generated server-side and embedded in the page's inline
JavaScript as a FormData.append() call:

    formData.append('nonce', '<10-char hex string>');

It must be extracted from a fresh GET of the careers page before each AJAX
call.

Response format
---------------
The endpoint returns JSON:  {"success": true, "data": "<html fragment>"}

The HTML fragment contains one block per job.  Each job has an <a> element
linking to a LinkedIn job posting (HAYA posts all openings on LinkedIn).
The link text is the job title.  Location is inferred from text within the
same card element.

All job URLs are LinkedIn links — there are no internal HAYA job detail pages.
"""

import json
import logging
import re

from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL     = "https://www.hayatx.com"
_CAREERS_URL = f"{BASE_URL}/careers/"
_AJAX_URL    = f"{BASE_URL}/wp-admin/admin-ajax.php"

# Primary nonce pattern: FormData.append('nonce', '<value>')
_NONCE_RE = re.compile(
    r"""formData\.append\(\s*['"]nonce['"]\s*,\s*['"]([^'"]+)['"]\s*\)""",
    re.IGNORECASE,
)
# Fallback: any JS object/assignment with a "nonce" key
_NONCE_FALLBACK_RE = re.compile(
    r"""['"]nonce['"]\s*[,:]\s*['"]([a-f0-9]{8,})['"]""",
    re.IGNORECASE,
)

# LinkedIn job URL pattern
_LINKEDIN_RE = re.compile(r"linkedin\.com/jobs/view/", re.IGNORECASE)

# Known Swiss city names for location inference
_SWISS_CITIES = ("lausanne", "geneva", "genève", "geneve", "zürich", "zurich",
                 "basel", "bern", "zug")


class HayaTxScraper(BaseScraper):
    """Scrapes job listings from HAYA Therapeutics via WordPress AJAX."""

    def __init__(
        self,
        company: str,
        location_terms: list[str],
        title_terms: list[str],
    ) -> None:
        self.company        = company
        self.careers_url    = _CAREERS_URL
        self.location_terms = location_terms
        self.title_terms    = title_terms

    # ------------------------------------------------------------------
    # BaseScraper interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        session = self.build_session()

        # Phase 1: fetch careers page to extract the per-request nonce
        resp = self._get_with_retry(session, _CAREERS_URL)
        if resp is None:
            logger.error("[%s] Failed to fetch careers page", self.company)
            return []

        nonce = self._extract_nonce(resp.text)
        if not nonce:
            logger.error("[%s] Could not extract AJAX nonce — cannot load jobs", self.company)
            return []
        logger.info("[%s] Nonce extracted: %s…", self.company, nonce[:6])

        # Phase 2: AJAX call to load all jobs
        payload = {
            "action":          "load_jobs_filter",
            "filter":          "all",
            "limit":           100,
            "offset":          0,
            "nonce":           nonce,
            "theme":           "dark",
            "animated_border": "0",
            "fixed_height":    "0",
            "gallery":         "0",
        }
        ajax_resp = self._post_with_retry(session, _AJAX_URL, data=payload)
        if ajax_resp is None:
            logger.error("[%s] AJAX request failed", self.company)
            return []

        # Phase 3: parse jobs from the HTML fragment in the response
        html_fragment = self._unwrap_response(ajax_resp.text)
        if not html_fragment:
            logger.warning("[%s] Empty AJAX response body", self.company)
            return []

        jobs = self._parse_jobs(html_fragment)
        logger.info("[%s] %d jobs collected", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_nonce(self, page_html: str) -> str | None:
        """Extract the WordPress nonce from the careers page inline JS."""
        m = _NONCE_RE.search(page_html)
        if m:
            return m.group(1)
        m = _NONCE_FALLBACK_RE.search(page_html)
        return m.group(1) if m else None

    def _unwrap_response(self, raw: str) -> str:
        """Extract the HTML fragment from a JSON envelope if present."""
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                # wp_send_json_success: {"success": true, "data": "<html>"}
                return data.get("data") or data.get("html") or ""
        except (json.JSONDecodeError, ValueError):
            pass
        return raw  # response was raw HTML directly

    def _parse_jobs(self, html: str) -> list[Job]:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[Job]     = []
        seen_urls: set[str] = set()

        for link in soup.find_all("a", href=_LINKEDIN_RE):
            href = link.get("href", "").strip()
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            title = link.get_text(strip=True)
            if not title:
                continue

            location = self._infer_location(link)

            jobs.append(Job(
                title=title,
                company=self.company,
                location=location,
                url=href,
            ))

        return jobs

    def _infer_location(self, link_el) -> str:
        """Walk up the DOM tree to find a city name in the card's text."""
        node = link_el.parent
        for _ in range(5):
            if node is None:
                break
            text = node.get_text(" ", strip=True).lower()
            for city in _SWISS_CITIES:
                if city in text:
                    # Capitalise first letter for display
                    display = city.capitalize()
                    if "switzerland" not in text:
                        return f"{display}, Switzerland"
                    return display
            if "san diego" in text:
                return "San Diego, USA"
            node = node.parent
        return "Switzerland"
