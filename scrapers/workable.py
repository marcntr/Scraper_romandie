"""Workable ATS scraper.

Two-phase fetch strategy (confirmed via live network interception):

Phase 1 — Job listing
  POST https://apply.workable.com/api/v3/accounts/{slug}/jobs
  Body: {"query":"","department":[],"location":[],"workplace":[],"worktype":[]}
  Response: {"total": N, "results": [...]}  ← key is "results", not "jobs"

  Each result contains: id, shortcode, title, remote, location, locations,
  state, department (list), workplace, published, etc.
  Crucially: no description fields are returned here.

Phase 2 — Per-job detail (needed for description / scoring)
  GET https://apply.workable.com/api/v1/accounts/{slug}/jobs/{shortcode}
  Response: same fields + "description", "requirements", "benefits" (all HTML)
  The "benefits" field is misnamed — it actually contains "Your profile" section
  which is where PhD / experience requirements appear.

Full scoring-ready description = strip_html(description + requirements + benefits).
"""

import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import cache as job_cache
from scrapers.base import BaseScraper
from models import Job

logger = logging.getLogger(__name__)

_API_LIST   = "https://apply.workable.com/api/v3/accounts/{slug}/jobs"
_API_DETAIL = "https://apply.workable.com/api/v1/accounts/{slug}/jobs/{shortcode}"

# Rate-limiting constants
_MIN_DELAY_S     = 0.3   # minimum polite inter-page delay (seconds)
_MAX_DELAY_S     = 0.8   # maximum polite inter-page delay
_PAGE_SIZE       = 50    # results per listing page
_PHASE2_WORKERS  = 4     # concurrent detail fetches within one company

# POST body sent to the listing endpoint — mirrors what the SPA sends
_LIST_BODY = {
    "query": "",
    "department": [],
    "location": [],
    "workplace": [],
    "worktype": [],
}


class WorkableScraper(BaseScraper):
    """Scraper for any company whose careers site is hosted on Workable."""

    def __init__(
        self,
        company: str,
        slug: str,
        location_terms: list[str] | None = None,
        title_terms: list[str] | None = None,
    ) -> None:
        self.company = company
        self.slug = slug
        self.careers_url = f"https://apply.workable.com/{slug}/"
        self._location_terms = location_terms or []
        self._title_terms = title_terms or []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        """Fetch all published jobs via the Workable JSON API (2-phase)."""
        session = self.build_session()

        # ── Phase 1: paginated listing ────────────────────────────────────
        list_url = _API_LIST.format(slug=self.slug)
        raw_results: list[dict] = []
        offset = 0

        while True:
            page_params = {"limit": _PAGE_SIZE, "offset": offset}
            resp = self._post_with_retry(session, list_url, _LIST_BODY, params=page_params)
            if resp is None:
                logger.error("[%s] Could not fetch listing page (offset=%d) — aborting",
                             self.company, offset)
                break

            try:
                data: dict = resp.json()
            except ValueError as exc:
                logger.error("[%s] Failed to parse listing JSON (offset=%d): %s",
                             self.company, offset, exc)
                break

            batch: list[dict] = data.get("results", [])
            if not batch:
                break  # empty page → done

            raw_results.extend(batch)

            total = data.get("total", 0)
            logger.info("[%s] Page offset=%d: %d results (collected %d / %s total)",
                        self.company, offset, len(batch), len(raw_results), total)

            # Stop conditions (checked in priority order):
            # 1. Collected everything the server declared → done
            # 2. No total declared AND short page → assume last page
            #    (short page alone is NOT sufficient when total > collected —
            #     some boards use a smaller internal page size than _PAGE_SIZE)
            if total and len(raw_results) >= total:
                break
            if not total and len(batch) < _PAGE_SIZE:
                break

            offset += _PAGE_SIZE
            time.sleep(random.uniform(_MIN_DELAY_S, _MAX_DELAY_S))

        logger.info("[%s] Phase 1 complete: %d jobs collected", self.company, len(raw_results))

        if not raw_results:
            return []

        # ── Phase 1.5: pre-filter on listing fields ───────────────────────
        # Avoids description fetches for irrelevant jobs when location/title
        # terms are configured.  The v3 API returns a location dict with
        # city/region/country so we can replicate the same checks cheaply.
        if self._location_terms or self._title_terms:
            candidates: list[dict] = []
            for raw in raw_results:
                title = (raw.get("title") or "").strip()
                # Build a combined location string from both the primary
                # "location" dict and every entry in the "locations" list so
                # that multi-country roles (e.g. UK / France / Switzerland)
                # are matched correctly.
                all_locs = [raw.get("location") or {}] + (raw.get("locations") or [])
                loc_str = " ".join(self._extract_location(l) for l in all_locs)
                if self._passes_prefilter(
                    title, loc_str, self._location_terms, self._title_terms
                ):
                    candidates.append(raw)
            logger.info("[%s] Pre-filter: %d / %d listings pass location + title",
                        self.company, len(candidates), len(raw_results))
            raw_results = candidates

        if not raw_results:
            return []

        # ── Phase 2: enrich each job with its description (parallel) ─────
        def _fetch_one(raw: dict) -> tuple[dict, dict | None, str | None]:
            shortcode = raw.get("shortcode") or raw.get("id") or ""
            apply_url = (
                f"https://apply.workable.com/{self.slug}/j/{shortcode}/"
                if shortcode else self.careers_url
            )
            cached = job_cache.get(apply_url)
            if cached:
                return raw, None, cached["description"]
            return raw, self._fetch_detail(session, shortcode), None

        jobs: list[Job] = []
        with ThreadPoolExecutor(max_workers=_PHASE2_WORKERS) as pool:
            for raw, detail, cached_desc in pool.map(_fetch_one, raw_results):
                job = self._parse_job(raw, detail, cached_desc)
                if job:
                    jobs.append(job)

        logger.info("[%s] Fetched %d jobs with descriptions", self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Phase 2 helper: per-job detail fetch
    # ------------------------------------------------------------------

    def _fetch_detail(self, session: requests.Session, shortcode: str) -> dict:
        """Fetch description/requirements/benefits for a single job shortcode."""
        if not shortcode:
            return {}
        url = _API_DETAIL.format(slug=self.slug, shortcode=shortcode)
        resp = self._get_with_retry(session, url)
        if resp is None:
            logger.warning("[%s] Could not fetch detail for %s", self.company, shortcode)
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_job(
        self,
        raw: dict,
        detail: dict | None,
        cached_description: str | None = None,
    ) -> Job | None:
        """Merge listing + detail dicts into a ``Job`` instance."""
        title = (raw.get("title") or "").strip()
        if not title:
            return None

        shortcode = raw.get("shortcode") or raw.get("id") or ""
        # Combine all locations for multi-country roles.
        all_locs = [raw.get("location") or {}] + (raw.get("locations") or [])
        location_str = " / ".join(
            filter(None, (self._extract_location(l) for l in all_locs))
        )
        posted = raw.get("published") or ""

        # department is a list in v3 API (e.g. ["Translational Medicine"])
        dept_raw = raw.get("department") or []
        department = ", ".join(dept_raw) if isinstance(dept_raw, list) else str(dept_raw)

        # URL is not returned by the listing API — construct from shortcode
        url = (
            f"https://apply.workable.com/{self.slug}/j/{shortcode}/"
            if shortcode
            else self.careers_url
        )

        if cached_description is not None:
            description = cached_description
        else:
            # Combine all three HTML description fields for full scoring coverage.
            # "benefits" is Workable's label for the "Your profile" section — where
            # PhD requirements and experience demands actually live.
            detail = detail or {}
            combined_html = " ".join(filter(None, [
                detail.get("description") or "",
                detail.get("requirements") or "",
                detail.get("benefits") or "",
            ]))
            description = self._strip_html(combined_html)
            job_cache.put(url, description, url)

        return Job(
            title=title,
            company=self.company,
            location=location_str,
            url=url,
            shortcode=shortcode,
            department=department,
            posted_date=posted[:10] if posted else "",
            description=description,
        )

    @staticmethod
    def _extract_location(loc: dict | str) -> str:
        """Normalise the Workable v3 location object into a readable string.

        v3 structure: {"country": "Switzerland", "countryCode": "CH",
                       "city": "Lausanne", "region": "Vaud"}
        No "location_str" or "telecommuting" fields in v3.
        """
        if isinstance(loc, str):
            return loc
        if not isinstance(loc, dict):
            return "Location not specified"

        parts: list[str] = []

        remote = loc.get("remote") or loc.get("telecommuting") or False
        if remote:
            parts.append("Remote")

        city    = (loc.get("city")    or "").strip()
        region  = (loc.get("region")  or "").strip()
        country = (loc.get("country") or "").strip()

        # Prefer city + country for clarity; include region when it adds info
        # (e.g. "Vaud" is a meaningful filter term for our location matching)
        if city and region and region.lower() != city.lower():
            parts.extend([city, region, country])
        else:
            parts.extend(filter(None, [city, country]))

        return ", ".join(filter(None, parts)) if parts else "Location not specified"
