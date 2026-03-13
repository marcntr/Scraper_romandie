"""Scraper for Stettler Consulting (Swiss healthcare recruiter — WordPress / YMC Smart Filter).

How it works
------------
The job listings page (`/en/find-jobs/`) uses the *YMC Smart Filter* WordPress
plugin (filter ID 662) to render all job cards via a single AJAX request.
The plugin embeds a short-lived WP nonce in the page's inline JavaScript;
we must fetch it fresh on each run.

API call
--------
POST https://www.stettlerconsulting.ch/wp-admin/admin-ajax.php
  action      = ymc_get_posts
  nonce_code  = <extracted from page>
  params      = <JSON blob from data-params attribute>
  paged       = 1

The response is a JSON object:
  {
    "data": "<HTML fragment containing <article> elements>",
    "found": 22,
    "max_num_pages": 1,
    ...
  }

Card structure (inside each <article>)
---------------------------------------
  - Title     : first <a href="..."> with a title attribute  (or fallback <h4>)
  - URL       : same first <a>[href]
  - Location  : 3rd <span class="btn-secondary-dark"> → <p> text
                e.g. "Mittelland", "Ostschweiz", "BE, JU, FR, NE",
                     "Region SG/AR/AI/GR/Liechtenstein"
                All are Swiss regions so ", Switzerland" is appended when missing.
"""

import html as _html
import json
import logging
import re

from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

_CAREERS_URL = "https://www.stettlerconsulting.ch/en/find-jobs/"
_AJAX_URL = "https://www.stettlerconsulting.ch/wp-admin/admin-ajax.php"


class StettlerScraper(BaseScraper):
    """Scrapes open positions from Stettler Consulting via YMC Smart Filter AJAX."""

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

        # ── Step 1: fetch the careers page to extract nonce + data-params ──
        resp = self._get_with_retry(session, _CAREERS_URL)
        if resp is None:
            logger.error("[%s] Failed to fetch careers page", self.company)
            return []

        nonce, params_json = self._extract_filter_config(resp.text)
        if not nonce or not params_json:
            logger.error("[%s] Could not extract YMC nonce/params", self.company)
            return []

        # ── Step 2: POST to the AJAX endpoint ──────────────────────────────
        post_data = {
            "action": "ymc_get_posts",
            "nonce_code": nonce,
            "params": params_json,
            "paged": "1",
        }
        try:
            ajax_resp = session.post(
                _AJAX_URL,
                data=post_data,
                timeout=30,
                headers=self._browser_headers(referer=_CAREERS_URL),
            )
            ajax_resp.raise_for_status()
        except Exception as exc:
            logger.error("[%s] AJAX POST failed: %s", self.company, exc)
            return []

        try:
            payload = ajax_resp.json()
        except ValueError:
            logger.error("[%s] AJAX response is not JSON", self.company)
            return []

        html_fragment = payload.get("data", "")
        total_found = payload.get("found", 0)
        logger.info("[%s] AJAX returned %d jobs", self.company, total_found)

        # ── Step 3: parse article cards from the HTML fragment ─────────────
        jobs: list[Job] = []
        soup = BeautifulSoup(html_fragment, "lxml")
        for article in soup.find_all("article"):
            job = self._parse_article(article)
            if job:
                jobs.append(job)

        logger.info("[%s] %d jobs collected", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_filter_config(html: str) -> tuple[str, str]:
        """Return (nonce, params_json) embedded in the page HTML."""
        # Nonce is in: var _smart_filter_object = {"ajax_url":"...","nonce":"XXXX",...}
        nonce_m = re.search(r'"nonce"\s*:\s*"([a-f0-9]+)"', html)
        nonce = nonce_m.group(1) if nonce_m else ""

        # data-params is in: <div class="ymc-smart-filter-container ..." data-params='{...}'>
        # The attribute value is HTML-encoded (e.g. &quot; instead of "), so we must
        # unescape it before sending it in the POST body.
        params_m = re.search(r'data-params=\'({[^\']+})\'', html)
        if not params_m:
            params_m = re.search(r'data-params="({[^"]+})"', html)
        params_json = _html.unescape(params_m.group(1)) if params_m else ""

        return nonce, params_json

    def _parse_article(self, article) -> Job | None:
        # Title + URL: first link that has a meaningful title attribute
        first_link = article.find("a", href=True)
        if not first_link:
            return None

        title = first_link.get("title", "").strip()
        if not title:
            h4 = first_link.find("h4")
            title = h4.get_text(strip=True) if h4 else first_link.get_text(strip=True)
        if not title:
            return None

        url = first_link["href"].strip()

        # Location: spans with btn-secondary-dark class; 3rd one is the region
        spans = article.find_all("span", class_=lambda c: c and "btn-secondary-dark" in c if c else False)
        location = ""
        if len(spans) >= 3:
            p = spans[2].find("p")
            location = p.get_text(strip=True) if p else spans[2].get_text(strip=True)

        location = self._ensure_switzerland(location)

        return Job(
            title=title,
            company=self.company,
            location=location,
            url=url,
        )
