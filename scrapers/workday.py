"""Workday ATS scraper.

Two-phase fetch strategy (verified via live API probe):

Phase 1 — Paginated job listing
  POST https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{portal}/jobs
  Body: {"appliedFacets": {}, "searchText": "", "limit": N, "offset": N}
  NOTE: limit and offset live INSIDE the JSON body (not query params).
  NOTE: "appliedFacets": {} is required — omitting it causes a 400.
  Response: {"total": int, "jobPostings": [...], "facets": [...], "userAuthenticated": bool}

  Each posting: title, externalPath, locationsText, postedOn, bulletFields
  No description fields at listing stage.

Phase 1.5 — In-memory pre-filter
  Apply location_terms + title_terms against title / locationsText from the
  listing before making any detail calls.  For US-heavy companies with
  ~1 000 total jobs and ~5 Swiss roles this reduces Phase 2 calls by ~99%.
  When search_fallback_terms has multiple entries, one paginated pass is made
  per term; results are deduplicated by externalPath before pre-filtering.

Phase 2 — Per-job detail fetch (description only)
  GET https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{portal}{externalPath}
  IMPORTANT: no "/jobs" segment in the detail path — returns 406 if included.
  Description HTML : response["jobPostingInfo"]["jobDescription"]
  Public URL       : response["jobPostingInfo"]["externalUrl"]
"""

import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

from scrapers.base import BaseScraper
from models import Job

logger = logging.getLogger(__name__)

# Rate-limiting constants
_MIN_DELAY_S     = 0.3   # minimum polite inter-page delay (seconds) — same-session, cookies established
_MAX_DELAY_S     = 0.8   # maximum polite inter-page delay
_PAGE_SIZE       = 20    # confirmed working value from live probe; raise cautiously
_PHASE2_WORKERS  = 4     # concurrent detail fetches within one company (independent GETs)

# Fixed POST body fields — limit and offset are injected per page.
# NOTE: "appliedFacets": {} is required by Workday schema validation — 400 without it.
# NOTE: "locations": [] causes a 400 on all tested Workday tenants — omit it.
_LIST_BODY_BASE: dict = {
    "appliedFacets": {},
    "searchText": "",
}

# Country / language name variants used when auto-detecting Switzerland facets.
_SWISS_TERMS = frozenset({"switzerland", "suisse", "schweiz", "svizzera", "swiss"})

# Regex for Workday's relative date strings: "Posted Today", "Posted 3 Days Ago",
# "Posted 30+ Days Ago".  These are converted to approximate ISO dates at parse
# time so the dashboard sort (date desc, score desc) works correctly for all
# Workday companies.
_POSTED_DAYS_RE = re.compile(r"(\d+)\+?\s*day", re.IGNORECASE)


def _parse_workday_date(posted_on: str) -> str:
    """Convert a Workday relative date string to 'YYYY-MM-DD', or '' if unknown."""
    if not posted_on:
        return ""
    s = posted_on.strip().lower()
    if "today" in s:
        return date.today().isoformat()
    m = _POSTED_DAYS_RE.search(s)
    if m:
        return (date.today() - timedelta(days=int(m.group(1)))).isoformat()
    return ""


class WorkdayScraper(BaseScraper):
    """Scraper for any company whose careers site is hosted on Workday.

    Pass ``location_terms`` and ``title_terms`` to enable the Phase 1.5
    pre-filter, which prevents fetching descriptions for thousands of
    irrelevant jobs at large multinational companies.

    ``search_fallback_terms`` controls what searchText values are used when
    the facet probe finds no Swiss location facet.  One paginated pass is made
    per term; results are deduplicated by externalPath.  Defaults to
    ["Switzerland"], which works for US-heavy companies.  For Swiss-HQ
    companies (Roche, Novartis, …) pass the actual city names so jobs whose
    listings say "Basel" (without "Switzerland") are still captured.
    """

    def __init__(
        self,
        company: str,
        tenant: str,
        instance: str,
        portal: str,
        location_terms: list[str] | None = None,
        title_terms: list[str] | None = None,
        location_facets: dict | None = None,
        search_fallback_terms: list[str] | None = None,
    ) -> None:
        self.company = company
        self.tenant = tenant
        self.instance = instance
        self.portal = portal
        self._location_terms = location_terms or []
        self._title_terms = title_terms or []
        self._location_facets = location_facets or {}
        self._search_fallback_terms: list[str] = search_fallback_terms or ["Switzerland"]

        self._base_url    = f"https://{tenant}.{instance}.myworkdayjobs.com"
        self._list_url    = f"{self._base_url}/wday/cxs/{tenant}/{portal}/jobs"
        self._detail_base = f"{self._base_url}/wday/cxs/{tenant}/{portal}"
        # Human-readable careers URL used as Referer header and fallback link
        self.careers_url  = f"{self._base_url}/en-US/{portal}/jobs"
        # Populated by _detect_location_facets when facet probe fails.
        # Each term drives one independent paginated pass; results are merged.
        self._search_texts: list[str] = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_jobs(self) -> list[Job]:
        """Fetch all relevant jobs via the Workday JSON API (2-phase)."""
        session = self.build_session()

        # ── Session warm-up: earn Cloudflare __cf_bm / PLAY_SESSION cookies ──
        self._warm_up_session(session)

        # ── Facet probe: restrict Phase 1 to Switzerland only ─────────────
        # One cheap call (limit=1) retrieves the facets array, from which we
        # extract the Workday-internal ID(s) for "Switzerland".  Injecting
        # these into appliedFacets means the listing API returns only Swiss
        # jobs — turning a 2 000-row Abbott or 979-row Roche crawl into a
        # handful of pages.  Falls back to full pagination if probe fails or
        # no Swiss facet is found.
        if not self._location_facets and self._location_terms:
            self._location_facets = self._detect_location_facets(session)

        # ── Phase 1: paginated listing ────────────────────────────────────
        # When location facets are active we do a single pass with searchText="".
        # When the facet probe fell back to city/country search terms we do one
        # paginated pass per term and deduplicate by externalPath so that jobs
        # whose listing contains multiple matching terms aren't counted twice.
        search_terms: list[str] = self._search_texts if self._search_texts else [""]
        all_raw: list[dict] = []
        seen_paths: set[str] = set()

        for term_idx, search_text in enumerate(search_terms):
            offset = 0
            expected_total = 0
            term_count = 0    # new unique items added to all_raw this term
            fetched = 0       # total items returned by server this term (incl. dupes)

            while True:
                page_body = {
                    **_LIST_BODY_BASE,
                    "appliedFacets": self._location_facets,
                    "searchText": search_text,
                    "limit": _PAGE_SIZE,
                    "offset": offset,
                }
                resp = self._post_with_retry(session, self._list_url, page_body)
                if resp is None:
                    logger.error("[%s] Listing failed at offset=%d — aborting",
                                 self.company, offset)
                    break

                try:
                    data: dict = resp.json()
                except ValueError as exc:
                    logger.error("[%s] JSON parse failed (offset=%d): %s",
                                 self.company, offset, exc)
                    break

                batch: list[dict] = data.get("jobPostings", [])
                if not batch:
                    break

                fetched += len(batch)

                # Deduplicate across search terms by externalPath.
                for item in batch:
                    path = item.get("externalPath") or ""
                    if path and path in seen_paths:
                        continue
                    if path:
                        seen_paths.add(path)
                    all_raw.append(item)
                    term_count += 1

                # Some Workday tenants omit or zero out "total" on pages after
                # the first — retain the last known non-zero value instead.
                expected_total = data.get("total") or expected_total
                label = f" (term='{search_text}')" if search_text else ""
                logger.info("[%s]%s Page offset=%d: %d results (collected %d / %d total)",
                            self.company, label, offset, len(batch),
                            len(all_raw), expected_total)

                # Stop conditions (priority order):
                # 1. Server declared a total — stop once we've fetched that many
                #    rows (use raw fetched count, not deduplicated, so overlapping
                #    terms from multi-term searches don't prevent termination).
                # 2. No total declared AND short page → assume last page.
                if expected_total and fetched >= expected_total:
                    break
                if not expected_total and len(batch) < _PAGE_SIZE:
                    break

                offset += _PAGE_SIZE
                time.sleep(random.uniform(_MIN_DELAY_S, _MAX_DELAY_S))

            logger.info("[%s] Term '%s': %d listings (running total: %d)",
                        self.company, search_text or "(none)", term_count, len(all_raw))

            # Brief pause between search terms to avoid hammering the same tenant.
            if term_idx < len(search_terms) - 1:
                time.sleep(random.uniform(_MIN_DELAY_S, _MAX_DELAY_S))

        logger.info("[%s] Phase 1 complete: %d listings collected",
                    self.company, len(all_raw))

        if not all_raw:
            return []

        # ── Phase 1.5: pre-filter on raw listing fields ───────────────────
        # Check location and title directly on the raw dict — no Job object
        # needed — to avoid building thousands of throwaway objects for
        # large companies (Pfizer, GSK…) before the detail-fetch phase.
        candidates: list[dict] = []
        for raw in all_raw:
            title = (raw.get("title") or "").strip()
            if not title:
                continue
            loc_str = (raw.get("locationsText") or "").lower()
            title_lower = title.lower()
            loc_ok   = (not self._location_terms
                        or any(t.lower() in loc_str for t in self._location_terms))
            title_ok = (not self._title_terms
                        or any(t.lower() in title_lower for t in self._title_terms))
            if loc_ok and title_ok:
                candidates.append(raw)

        logger.info("[%s] Pre-filter: %d / %d listings pass location + title",
                    self.company, len(candidates), len(all_raw))

        if not candidates:
            return []

        # ── Phase 2: description fetch for each candidate (parallel) ─────
        # Each worker gets its own session initialised with the warm-up
        # cookies so requests.Session is never shared across threads.
        cookies = {c.name: c.value for c in session.cookies}

        def _fetch_one(raw: dict) -> tuple[dict, dict]:
            s = self.build_session()
            s.cookies.update(cookies)
            return raw, self._fetch_detail(s, raw.get("externalPath", ""))

        jobs: list[Job] = []
        with ThreadPoolExecutor(max_workers=_PHASE2_WORKERS) as pool:
            for raw, detail in pool.map(_fetch_one, candidates):
                job = self._parse_job(raw, detail)
                if job:
                    jobs.append(job)

        logger.info("[%s] Phase 2 complete: %d jobs with descriptions",
                    self.company, len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Phase 2 helper
    # ------------------------------------------------------------------

    def _fetch_detail(self, session: requests.Session, external_path: str) -> dict:
        """Fetch jobPostingInfo for a single job.

        Detail URL = CXS portal base + externalPath (no '/jobs' segment).
        """
        if not external_path:
            return {}
        url = f"{self._detail_base}{external_path}"
        resp = self._get_with_retry(session, url)
        if resp is None:
            logger.warning("[%s] Detail fetch failed for %s",
                           self.company, external_path)
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_job(self, raw: dict, detail: dict) -> Job | None:
        """Merge listing + detail response into a Job instance."""
        title = (raw.get("title") or "").strip()
        if not title:
            return None

        # locationsText is a clean string already: "Lausanne, Switzerland"
        location = (raw.get("locationsText") or "").strip()

        # bulletFields[0] contains the job req ID when present
        bullets = raw.get("bulletFields") or []
        req_id  = bullets[0].strip() if bullets else ""

        posted = _parse_workday_date(raw.get("postedOn") or "")

        info = detail.get("jobPostingInfo", {})

        # Public URL from the detail response; fall back to company search page
        public_url = (info.get("externalUrl") or "").strip() or self.careers_url

        # Full HTML description from the detail response
        raw_html    = info.get("jobDescription") or ""
        description = self._strip_html(raw_html)

        return Job(
            title=title,
            company=self.company,
            location=location,
            url=public_url,
            shortcode=req_id,
            department="",      # not provided by the Workday API
            posted_date=posted,
            description=description,
        )

    # ------------------------------------------------------------------
    # HTTP helpers — warm-up (_post_with_retry is inherited from BaseScraper)
    # ------------------------------------------------------------------

    def _warm_up_session(self, session: requests.Session) -> None:
        """GET the public careers page to earn Cloudflare cookies.

        Cloudflare Bot Management requires __cf_bm and PLAY_SESSION to be
        present on API POST requests.  A real browser always loads the careers
        page before making any XHR calls; this replicates that behaviour so
        the subsequent POST is not flagged as a cold bot session.
        """
        try:
            resp = session.get(
                self.careers_url,
                timeout=20,
                headers=self._browser_headers(),
            )
            logger.debug(
                "[%s] Warm-up GET %s → %d",
                self.company, self.careers_url, resp.status_code,
            )
        except Exception as exc:
            logger.warning(
                "[%s] Warm-up GET failed (continuing): %s",
                self.company, exc,
            )
        time.sleep(random.uniform(1.5, 3.0))

    def _detect_location_facets(self, session: requests.Session) -> dict:
        """Probe the listing endpoint (limit=1) to auto-discover the Workday
        facet parameter and ID(s) that correspond to Switzerland.

        Workday returns a ``facets`` array on every listing response.  Each
        facet has a ``facetParameter`` key (e.g. ``"Locations_0"``) and a
        ``values`` list of ``{value, count, id}`` dicts.  We scan for any
        value whose display name contains a Swiss country/language term and
        return ``{facetParameter: [id, ...]}`` for use as ``appliedFacets``.

        Returns ``{}`` if the probe fails or no Swiss facet is found, which
        causes ``fetch_jobs`` to fall back to full global pagination.
        """
        probe_body = {**_LIST_BODY_BASE, "appliedFacets": {}, "limit": 1, "offset": 0}
        resp = self._post_with_retry(session, self._list_url, probe_body)
        if resp is None:
            return {}
        try:
            data = resp.json()
        except ValueError:
            return {}

        for facet in (data.get("facets") or []):
            param = facet.get("facetParameter") or ""
            if "location" not in param.lower():
                continue
            swiss_ids = [
                v["id"]
                for v in (facet.get("values") or [])
                if any(t in (v.get("value") or "").lower() for t in _SWISS_TERMS)
                and v.get("id")
            ]
            if swiss_ids:
                logger.info(
                    "[%s] Facet probe: %d Swiss location ID(s) found under '%s' — "
                    "Phase 1 will fetch Swiss jobs only",
                    self.company, len(swiss_ids), param,
                )
                return {param: swiss_ids}

        logger.info(
            "[%s] Facet probe: no Switzerland facet detected — "
            "falling back to searchText terms: %s",
            self.company, self._search_fallback_terms,
        )
        self._search_texts = self._search_fallback_terms
        return {}

