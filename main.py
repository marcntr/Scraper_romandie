"""Job scraper orchestrator — Phase 2 POC (Workable / Debiopharm).

Run:
    python main.py            # filtered + scored results, sorted by score
    python main.py --all      # show all open positions first, then filtered
"""

import argparse
import json
import logging
import os
import random
import sys
import time
import urllib.request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import cache as job_cache
from config import COMPANIES, GIST_ID, LOCATION_FILTERS, TITLE_FILTERS
from export_html import export_html
from filters import apply_filters, explain_job, score_job
from models import Job
from scrapers.generic_monitor import GenericMonitor
from scrapers.alecallan import AlecAllanScraper
from scrapers.ashby import AshbyScraper
from scrapers.gloorlang import GloorLangScraper
from scrapers.greenhouse import GreenhouseScraper
from scrapers.hayatx import HayaTxScraper
from scrapers.hays import HaysScraper
from scrapers.incyte import IncyteScraper
from scrapers.michaelpage import MichaelPageScraper
from scrapers.nestlehealthscience import NestleHealthScienceScraper
from scrapers.paylocity import PaylocityScraper
from scrapers.randstad import RandstadScraper
from scrapers.smartrecruiters import SmartRecruitersScraper
from scrapers.stettler import StettlerScraper
from scrapers.successfactors import SuccessFactorsScraper
from scrapers.personio import PersonioScraper
from scrapers.teamtailor import TeamtailorScraper
from scrapers.workable import WorkableScraper
from scrapers.workday import WorkdayScraper

# ---------------------------------------------------------------------------
# Logging — timestamps to stderr, clean format
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

DIVIDER = "─" * 70

# Max concurrent threads for non-Workday ATS types (Greenhouse, Paylocity,
# SuccessFactors, Workable, Generic).  These all hit independent domains so
# there is no shared-IP rate-limit concern.
_OTHER_WORKERS = 20


# ---------------------------------------------------------------------------
# Gist status sync — pull applied/ignored statuses into the cache so that
# jobs marked from any device (phone etc.) survive scraper pruning.
# ---------------------------------------------------------------------------

def _sync_gist_statuses(gist_id: str) -> None:
    """Fetch statuses.json from the Gist and apply any non-matched statuses
    to the local cache.  Called once after cache.load(), before scraping.

    Secret Gists are accessible anonymously when you know the ID, so no
    authentication token is needed.  Any network or parse error is logged
    and silently ignored so a Gist outage never blocks the scraper.
    """
    if not gist_id:
        return
    url = f"https://api.github.com/gists/{gist_id}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        raw = data.get("files", {}).get("statuses.json", {}).get("content", "{}")
        statuses: dict = json.loads(raw)
    except Exception as exc:
        logger.warning("Gist sync: could not fetch statuses — %s", exc)
        return

    applied = sum(1 for s in statuses.values() if s == "applied")
    for job_url, status in statuses.items():
        if status in ("matched", "ignored", "applied"):
            job_cache.set_status(job_url, status)
    logger.info("Gist sync: applied %d status(es) (%d applied) from Gist %s",
                len(statuses), applied, gist_id)


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

# Required fields per ATS type (beyond "name" and "ats" which are always needed)
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "workable":        ["slug"],
    "workday":         ["tenant", "instance", "portal"],
    "paylocity":       ["company_guid", "company_slug"],
    "greenhouse":      ["board_token"],
    "successfactors":  ["careers_url"],
    "smartrecruiters": ["company_id"],
    "ashby":           ["slug"],
    "personio":        ["subdomain"],
    "teamtailor":      ["subdomain", "api_token"],
    "generic":         ["careers_url"],
}


def _validate_companies(companies: list[dict]) -> None:
    """Log an error for every company config that is missing required fields.

    Does not raise — a misconfigured company is skipped at scrape time, not at
    startup, so a single bad entry never blocks the rest of the run.
    """
    errors: list[str] = []
    for cfg in companies:
        name = cfg.get("name") or "(unnamed)"
        ats  = cfg.get("ats")
        if not ats:
            errors.append(f"  {name}: missing 'ats' field")
            continue
        for field in _REQUIRED_FIELDS.get(ats, []):
            if not cfg.get(field):
                errors.append(f"  {name} ({ats}): missing required field '{field}'")

    if errors:
        logger.error(
            "Config validation failed — %d error(s):\n%s",
            len(errors), "\n".join(errors),
        )
    else:
        logger.info("Config validation: all %d companies OK", len(companies))


# ---------------------------------------------------------------------------
# Per-company term resolution
# ---------------------------------------------------------------------------

def _resolve_terms(cfg: dict) -> tuple[list[str], list[str]]:
    """Return the (location_terms, title_terms) that apply to this company.

    Falls back to the global LOCATION_FILTERS / TITLE_FILTERS unless the
    company config overrides them (e.g. Nestlé's ", CH"-only location terms).
    This is the single source of truth for term resolution — both
    ``_build_scraper`` (Phase 1.5 pre-filter inside the scraper) and
    ``_scrape_one`` (final ``apply_filters()`` gate) call it, so a
    per-company override can no longer narrow the pre-filter while the
    final gate silently falls back to the global list.
    """
    return (
        cfg.get("location_terms", LOCATION_FILTERS),
        cfg.get("title_terms", TITLE_FILTERS),
    )


# ---------------------------------------------------------------------------
# Scraper factory
# ---------------------------------------------------------------------------

def _build_scraper(cfg: dict):
    ats = cfg["ats"]
    name = cfg["name"]
    location_terms, title_terms = _resolve_terms(cfg)

    if ats == "workable":
        return WorkableScraper(
            company=name,
            slug=cfg["slug"],
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "workday":
        return WorkdayScraper(
            company=name,
            tenant=cfg["tenant"],
            instance=cfg["instance"],
            portal=cfg["portal"],
            location_terms=location_terms,
            title_terms=title_terms,
            location_facets=cfg.get("location_facets", {}),
            search_fallback_terms=cfg.get("search_fallback_terms"),
        )

    if ats == "paylocity":
        return PaylocityScraper(
            company=name,
            company_guid=cfg["company_guid"],
            company_slug=cfg["company_slug"],
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "greenhouse":
        return GreenhouseScraper(
            company=name,
            board_token=cfg["board_token"],
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "successfactors":
        return SuccessFactorsScraper(
            company=name,
            careers_url=cfg["careers_url"],
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "randstad":
        return RandstadScraper(
            company=name,
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "gloorlang":
        return GloorLangScraper(
            company=name,
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "stettler":
        return StettlerScraper(
            company=name,
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "alecallan":
        return AlecAllanScraper(
            company=name,
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "hays":
        return HaysScraper(
            company=name,
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "michaelpage":
        return MichaelPageScraper(
            company=name,
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "hayatx":
        return HayaTxScraper(
            company=name,
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "smartrecruiters":
        return SmartRecruitersScraper(
            company=name,
            company_id=cfg["company_id"],
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "nestlehealthscience":
        return NestleHealthScienceScraper(
            company=name,
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "ashby":
        return AshbyScraper(
            company=name,
            slug=cfg["slug"],
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "personio":
        return PersonioScraper(
            company=name,
            subdomain=cfg["subdomain"],
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "teamtailor":
        return TeamtailorScraper(
            company=name,
            subdomain=cfg["subdomain"],
            api_token=cfg["api_token"],
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "incyte":
        return IncyteScraper(
            company=name,
            location_terms=location_terms,
            title_terms=title_terms,
        )

    if ats == "generic":
        return GenericMonitor(
            company=name,
            careers_url=cfg["careers_url"],
            keywords=cfg.get("keywords", title_terms),
        )

    logger.warning("Scraper for ATS '%s' not yet implemented — skipping %s", ats, name)
    return None


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_job_table(jobs: list[Job], header: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  {header}  ({len(jobs)} job{'s' if len(jobs) != 1 else ''})")
    print(DIVIDER)
    if not jobs:
        print("  (none)")
        return
    for j in jobs:
        dept = f"  [{j.department}]" if j.department else ""
        date = f"  posted {j.posted_date}" if j.posted_date else ""
        print(f"\n  Title    : {j.title}{dept}")
        print(f"  Company  : {j.company}")
        print(f"  Location : {j.location}{date}")
        print(f"  URL      : {j.url}")
        # Score fields — only shown after scoring has been applied
        if j.score != 0 or j.matched_keywords or j.deducted_keywords:
            print(f"  Score    : {j.score:+d}")
        if j.matched_keywords:
            print(f"  +Keywords: {', '.join(j.matched_keywords)}")
        if j.deducted_keywords:
            print(f"  -Keywords: {', '.join(j.deducted_keywords)}")
        if j.description:
            print(f"  Description:\n")
            for line in j.description[:2000].splitlines():
                print(f"    {line}")
            if len(j.description) > 2000:
                print(f"    […truncated]")


# ---------------------------------------------------------------------------
# Per-company scrape helper (called from thread pool for non-Workday ATS)
# ---------------------------------------------------------------------------

def _explain_matches(jobs: list[Job], cfg: dict, explain_term: str) -> None:
    """Print a filter verdict for every scraped job whose title, location,
    company, or URL contains ``explain_term`` (case-insensitive).

    This runs against the *unfiltered* job list so it also surfaces jobs
    that a scraper's own Phase 1.5 pre-filter already dropped — the
    exact class of false negative this flag exists to diagnose.
    """
    term_lower = explain_term.lower()
    location_terms, title_terms = _resolve_terms(cfg)
    for j in jobs:
        haystack = f"{j.title} {j.location} {j.company} {j.url}".lower()
        if term_lower not in haystack:
            continue
        verdict = explain_job(j, location_terms, title_terms)
        print(f"\n  [EXPLAIN] {cfg['name']}: {j.title!r} @ {j.location!r}")
        print(f"            {verdict}")
        print(f"            url: {j.url}")


def _scrape_one(
    cfg: dict,
    show_all: bool = False,
    explain_term: str | None = None,
) -> tuple[list[Job], set[str], list[tuple[str, str]]]:
    """Scrape a single company.

    Returns:
        matched_jobs:    Jobs that passed location + title filters (scored).
        all_scraped_urls: URLs of every job seen before filtering — used by
                          prune_and_save so jobs that exist but didn't match
                          today are not evicted from the description cache.
        generic_alerts:  (company, alert_str) pairs from GenericMonitor hits.
    """
    scraper = _build_scraper(cfg)
    if scraper is None:
        return [], set(), []

    logger.info("── Scraping %s (%s) ──", cfg["name"], cfg["ats"])

    if isinstance(scraper, GenericMonitor):
        alert = scraper.check()
        return [], set(), ([(cfg["name"], alert)] if alert else [])

    all_jobs = scraper.fetch_jobs()

    if show_all:
        _print_job_table(all_jobs, f"ALL OPEN POSITIONS — {cfg['name']}")

    if explain_term:
        _explain_matches(all_jobs, cfg, explain_term)

    all_scraped_urls = {j.url for j in all_jobs}
    location_terms, title_terms = _resolve_terms(cfg)
    matched = apply_filters(all_jobs, location_terms, title_terms)
    matched = [score_job(j) for j in matched]
    for j in matched:
        j.status = job_cache.get_status(j.url)
        job_cache.update_snapshot(j.url, j)
    logger.info(
        "[%s] %d total open | %d passed filters",
        cfg["name"], len(all_jobs), len(matched),
    )
    return matched, all_scraped_urls, []


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run(
    show_all: bool = False,
    explain_term: str | None = None,
    company_filter: str | None = None,
) -> list[Job]:
    job_cache.load()
    _sync_gist_statuses(GIST_ID)
    _validate_companies(COMPANIES)
    # Snapshot pre-run cache so export_html can mark genuinely new jobs.
    pre_run_urls = job_cache.known_urls()

    all_matched: list[Job] = []
    all_scraped_urls: set[str] = set()
    generic_alerts: list[tuple[str, str]] = []

    companies = COMPANIES
    if company_filter:
        needle = company_filter.lower()
        companies = [c for c in COMPANIES if needle in c["name"].lower()]
        if not companies:
            logger.error("--company %r matched no configured company", company_filter)
            return []

    print(f"\n{'='*70}")
    print("  BIOPHARMA JOB SCRAPER")
    print(f"{'='*70}")
    print(f"  Location filters : {', '.join(LOCATION_FILTERS)}")
    print(f"  Title filters    : {', '.join(TITLE_FILTERS)}")
    if company_filter:
        print(f"  Company filter   : {company_filter!r} ({len(companies)} match(es))")
    if explain_term:
        print(f"  Explain term     : {explain_term!r}")
    print(f"{'='*70}\n")

    # ── Split companies by scraping constraint ────────────────────────────
    # Workday tenants share Cloudflare IP-level rate limiting — they MUST run
    # sequentially with 10-15 s gaps between cold sessions.
    # Every other ATS (Greenhouse, Workable, Paylocity, SuccessFactors, Generic)
    # hits independent domains and can run fully in parallel.
    workday_cfgs = [c for c in companies if c["ats"] == "workday"]
    other_cfgs   = [c for c in companies if c["ats"] != "workday"]

    # ── Launch non-Workday scrapers in a thread pool ──────────────────────
    # They start immediately and run overlapped with the Workday loop below.
    pool = ThreadPoolExecutor(max_workers=_OTHER_WORKERS, thread_name_prefix="scraper")
    other_futures = {
        pool.submit(_scrape_one, cfg, show_all, explain_term): cfg for cfg in other_cfgs
    }

    # ── Workday: sequential with mandatory inter-company delays ───────────
    for idx, cfg in enumerate(workday_cfgs):
        matched, urls, alerts = _scrape_one(cfg, show_all, explain_term)
        all_matched.extend(matched)
        all_scraped_urls.update(urls)
        generic_alerts.extend(alerts)

        if idx < len(workday_cfgs) - 1:
            delay = random.uniform(10.0, 15.0)
            logger.info("Waiting %.1fs before next Workday company…", delay)
            time.sleep(delay)

    # ── Collect non-Workday results ───────────────────────────────────────
    pool.shutdown(wait=True)
    for future, cfg in other_futures.items():
        try:
            matched, urls, alerts = future.result(timeout=300)
            all_matched.extend(matched)
            all_scraped_urls.update(urls)
            generic_alerts.extend(alerts)
        except FutureTimeoutError:
            logger.error(
                "[%s] Scraper timed out after 300 s — skipping", cfg["name"]
            )
        except Exception as exc:
            logger.error("[%s] Scraper thread raised: %s", cfg["name"], exc)

    # ------------------------------------------------------------------
    # Final output — filtered + scored, sorted by date desc then score desc.
    # Jobs with a missing/unparseable date are placed at the bottom.
    # ------------------------------------------------------------------
    def _sort_key(j: Job) -> tuple:
        try:
            date_val = datetime.strptime(j.posted_date, "%Y-%m-%d") if j.posted_date else None
        except ValueError:
            date_val = None
        # Sort ascending so that:
        #   (0, -timestamp, -score) — dated jobs, most-recent first, highest score first
        #   (1, 0, 0)               — undated jobs sink to the bottom
        if date_val is None:
            return (1, 0, 0)
        return (0, -date_val.timestamp(), -j.score)

    # ── Applied archive: re-inject jobs no longer live but previously applied ─
    # These are excluded from all_scraped_urls so prune_and_save would normally
    # remove them — but the immortality rule in prune_and_save keeps them in
    # seen_jobs.json.  We re-hydrate them here so the Applied tab stays intact.
    live_urls = {j.url for j in all_matched}
    for j in job_cache.get_applied_archive():
        if j.url not in live_urls:
            all_matched.append(j)

    all_matched.sort(key=_sort_key)
    _print_job_table(all_matched, "FILTERED & SCORED MATCHES (location + title)")

    print(f"\n{DIVIDER}")
    print(f"  Total matches: {len(all_matched)}")
    print(DIVIDER)

    # ------------------------------------------------------------------
    # Generic monitor alerts
    # ------------------------------------------------------------------
    print(f"\n{DIVIDER}")
    print(f"  GENERIC MONITOR ALERTS  ({len(generic_alerts)} alert{'s' if len(generic_alerts) != 1 else ''})")
    print(DIVIDER)
    if generic_alerts:
        for company, alert in generic_alerts:
            print(f"\n  Company : {company}")
            print(f"  Alert   : {alert}")
    else:
        print("  (none)")

    export_html(all_matched, generic_alerts, COMPANIES, known_urls=pre_run_urls)

    # Persist cache — prune entries for jobs no longer seen anywhere in this
    # run (filled / removed positions).  We pass all scraped URLs (pre-filter)
    # so that jobs which exist but didn't match today's criteria keep their
    # cached descriptions and won't be re-fetched next run.
    job_cache.prune_and_save(all_scraped_urls)

    return all_matched


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Biopharma job scraper")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print every open position (unfiltered) before showing scored matches",
    )
    parser.add_argument(
        "--explain",
        metavar="TERM",
        help=(
            "Debug a false negative: for every scraped job whose title, "
            "location, company, or URL contains TERM (case-insensitive), "
            "print which filter stage would accept/reject it and why. "
            "Runs against the unfiltered job list, so it also surfaces jobs "
            "a scraper's own pre-filter already dropped. Combine with "
            "--company to skip scraping everything else."
        ),
    )
    parser.add_argument(
        "--company",
        metavar="NAME",
        help="Only scrape companies whose name contains NAME (case-insensitive)",
    )
    args = parser.parse_args()
    run(show_all=args.all, explain_term=args.explain, company_filter=args.company)
