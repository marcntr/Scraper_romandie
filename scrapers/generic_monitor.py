"""Generic webpage monitor for companies without a structured ATS.

Strategy
--------
Rather than attempting to parse a structured Job object from an unstructured
careers page (fragile, regex-heavy, prone to infinite retry loops), this
monitor simply fetches the raw page, strips HTML, and checks for keyword
presence.  A match returns a plain alert string for manual review — no Job
object is produced.

Usage in config.py
------------------
    {
        "name": "Novigenix",
        "ats": "generic",
        "careers_url": "https://novigenix.com/career/",
        "keywords": TITLE_FILTERS,
    }
"""

import logging

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from models import Job

logger = logging.getLogger(__name__)

_TIMEOUT = 15


class GenericMonitor(BaseScraper):
    """Keyword-presence monitor for unstructured careers pages.

    Does NOT produce Job objects.  Returns an empty list (satisfying the
    BaseScraper interface) and logs an alert if any keyword is found.
    Call ``check()`` directly to get the alert string, or rely on
    ``fetch_jobs()`` for integration with the main pipeline.
    """

    def __init__(
        self,
        company: str,
        careers_url: str,
        keywords: list[str],
    ) -> None:
        self.company = company
        self.careers_url = careers_url
        self.keywords = [kw.lower() for kw in keywords]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def check(self) -> str | None:
        """Fetch the page and return an alert string if a keyword matches,
        or None if no match (or the page could not be fetched)."""
        session = self.build_session()
        try:
            resp = session.get(
                self.careers_url,
                timeout=_TIMEOUT,
                headers=self._browser_headers(referer=self.careers_url),
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.warning("[%s] GenericMonitor: failed to fetch %s — %s",
                           self.company, self.careers_url, exc)
            return None

        text = self._visible_text(resp.text)
        matched = [kw for kw in self.keywords if kw in text]

        if matched:
            alert = (
                f"Potential match found at {self.careers_url}. "
                f"Manual review required. "
                f"Matched keywords: {', '.join(matched)}"
            )
            logger.info("[%s] GenericMonitor ALERT: %s", self.company, alert)
            return alert

        logger.info("[%s] GenericMonitor: no keyword matches at %s",
                    self.company, self.careers_url)
        return None

    def fetch_jobs(self) -> list[Job]:
        """Satisfies BaseScraper interface. Always returns an empty list —
        use check() directly to retrieve the alert string."""
        return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _visible_text(html: str) -> str:
        """Strip all HTML tags and return lowercase visible text."""
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True).lower()
