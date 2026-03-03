"""Base scraper class shared by all ATS scrapers.

User-Agent strategy
-------------------
``fake_useragent.UserAgent`` is used to sample a realistic, up-to-date browser
UA on *every* HTTP call.  The session is intentionally left UA-free so that
per-request headers (injected by each subclass) always win.  This produces
genuine per-request rotation rather than the brittle "random once at session
creation" pattern.

A hardcoded modern fallback UA is used if the package fails to initialise
(network-restricted environment, corrupt cache, import error, etc.).
"""

import logging
import re
import time
from abc import ABC, abstractmethod

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# fake-useragent initialisation — defensive, never raises at import time
# ---------------------------------------------------------------------------
try:
    from fake_useragent import UserAgent
    # platforms=["desktop"] excludes mobile UAs (iPhone, Android, iPad).
    # Without this filter, the default pool is ~70% mobile in fake-useragent 2.x,
    # which causes failures on sites that serve different responses to mobile agents.
    _UA = UserAgent(platforms=["desktop"])
except Exception:
    _UA = None

_FALLBACK_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

from models import Job

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all ATS scrapers.

    Subclasses must implement ``fetch_jobs()`` which returns a raw list of
    ``Job`` objects (unfiltered).  Filtering and scoring are applied
    externally so the same pipeline works across all scrapers.
    """

    company: str
    careers_url: str

    # Shared retry constants — used by _get_with_retry and subclass _post_with_retry
    _MAX_RETRIES: int = 3
    _BACKOFF_BASE: float = 4.0

    # ------------------------------------------------------------------
    # Helpers available to all subclasses
    # ------------------------------------------------------------------

    def build_session(self) -> requests.Session:
        """Return a bare requests.Session with NO User-Agent pre-set.

        Headers (including a freshly sampled UA) are injected on each
        individual request via ``_browser_headers()`` so rotation is
        genuine — not just random-at-session-creation.
        """
        return requests.Session()

    def _browser_headers(self, referer: str | None = None) -> dict[str, str]:
        """Return a full set of browser-like headers with a fresh random UA."""
        headers = {
            "User-Agent": _UA.random if _UA else _FALLBACK_UA,
            "Accept": "application/json, text/html, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def _get_with_retry(
        self,
        session: requests.Session,
        url: str,
        params: dict | None = None,
    ) -> requests.Response | None:
        """GET with exponential backoff on 429 / transient network errors."""
        for attempt in range(self._MAX_RETRIES):
            try:
                resp = session.get(
                    url,
                    params=params or {},
                    timeout=20,
                    headers=self._browser_headers(referer=self.careers_url),
                )
                if resp.status_code == 429:
                    wait = float(resp.headers.get(
                        "Retry-After", self._BACKOFF_BASE * (2 ** attempt)))
                    logger.warning(
                        "[%s] GET 429 — backing off %.1fs (attempt %d/%d)",
                        self.company, wait, attempt + 1, self._MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except requests.exceptions.HTTPError as exc:
                status = getattr(exc.response, "status_code", 0)
                if status >= 500:
                    logger.warning(
                        "[%s] GET %d — backing off (attempt %d/%d)",
                        self.company, status, attempt + 1, self._MAX_RETRIES,
                    )
                    if attempt < self._MAX_RETRIES - 1:
                        time.sleep(self._BACKOFF_BASE * (2 ** attempt))
                        continue
                logger.error("[%s] Non-retryable GET error: %s", self.company, exc)
                return None
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as exc:
                logger.warning("[%s] Network error on GET attempt %d/%d: %s",
                               self.company, attempt + 1, self._MAX_RETRIES, exc)
                if attempt < self._MAX_RETRIES - 1:
                    time.sleep(self._BACKOFF_BASE * (2 ** attempt))
                else:
                    logger.error("[%s] GET max retries exhausted", self.company)
                    return None
        logger.error("[%s] GET gave up after persistent 429", self.company)
        return None

    @staticmethod
    def _strip_html(html: str) -> str:
        """Strip HTML tags and normalise whitespace. Caps output at 8 000 chars."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:8000]

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch_jobs(self) -> list[Job]:
        """Fetch ALL published jobs from this company's ATS. No filtering."""
        ...
