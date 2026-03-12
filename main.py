"""Job scraper orchestrator — Phase 2 POC (Workable / Debiopharm).

Run:
    python main.py            # filtered + scored results, sorted by score
    python main.py --all      # show all open positions first, then filtered
"""

import argparse
import logging
import os
import random
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import cache as job_cache
from config import COMPANIES, LOCATION_FILTERS, TITLE_FILTERS
from export_html import export_html
from filters import apply_filters, score_job
from models import Job
from scrapers.generic_monitor import GenericMonitor
from scrapers.alecallan import AlecAllanScraper
from scrapers.gloorlang import GloorLangScraper
from scrapers.greenhouse import GreenhouseScraper
from scrapers.hays import HaysScraper
from scrapers.paylocity import PaylocityScraper
from scrapers.randstad import RandstadScraper
from scrapers.stettler import StettlerScraper
from scrapers.successfactors import SuccessFactorsScraper
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
# Scraper factory
# ---------------------------------------------------------------------------

def _build_scraper(cfg: dict):
    ats = cfg["ats"]
    name = cfg["name"]

    if ats == "workable":
        return WorkableScraper(
            company=name,
            slug=cfg["slug"],
            location_terms=LOCATION_FILTERS,
            title_terms=TITLE_FILTERS,
        )

    if ats == "workday":
        return WorkdayScraper(
            company=name,
            tenant=cfg["tenant"],
            instance=cfg["instance"],
            portal=cfg["portal"],
            location_terms=LOCATION_FILTERS,
            title_terms=TITLE_FILTERS,
            location_facets=cfg.get("location_facets", {}),
            search_fallback_terms=cfg.get("search_fallback_terms"),
        )

    if ats == "paylocity":
        return PaylocityScraper(
            company=name,
            company_guid=cfg["company_guid"],
            company_slug=cfg["company_slug"],
            location_terms=LOCATION_FILTERS,
            title_terms=TITLE_FILTERS,
        )

    if ats == "greenhouse":
        return GreenhouseScraper(
            company=name,
            board_token=cfg["board_token"],
            location_terms=LOCATION_FILTERS,
            title_terms=TITLE_FILTERS,
        )

    if ats == "successfactors":
        return SuccessFactorsScraper(
            company=name,
            careers_url=cfg["careers_url"],
            location_terms=cfg.get("location_terms", LOCATION_FILTERS),
            title_terms=TITLE_FILTERS,
        )

    if ats == "randstad":
        return RandstadScraper(
            company=name,
            location_terms=LOCATION_FILTERS,
            title_terms=TITLE_FILTERS,
        )

    if ats == "gloorlang":
        return GloorLangScraper(
            company=name,
            location_terms=LOCATION_FILTERS,
            title_terms=TITLE_FILTERS,
        )

    if ats == "stettler":
        return StettlerScraper(
            company=name,
            location_terms=LOCATION_FILTERS,
            title_terms=TITLE_FILTERS,
        )

    if ats == "alecallan":
        return AlecAllanScraper(
            company=name,
            location_terms=LOCATION_FILTERS,
            title_terms=TITLE_FILTERS,
        )

    if ats == "hays":
        return HaysScraper(
            company=name,
            location_terms=LOCATION_FILTERS,
            title_terms=TITLE_FILTERS,
        )

    if ats == "generic":
        return GenericMonitor(
            company=name,
            careers_url=cfg["careers_url"],
            keywords=cfg.get("keywords", TITLE_FILTERS),
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

def _scrape_one(
    cfg: dict,
    show_all: bool = False,
) -> tuple[list[Job], list[tuple[str, str]]]:
    """Scrape a single company. Returns (matched_jobs, generic_alerts)."""
    scraper = _build_scraper(cfg)
    if scraper is None:
        return [], []

    logger.info("── Scraping %s (%s) ──", cfg["name"], cfg["ats"])

    if isinstance(scraper, GenericMonitor):
        alert = scraper.check()
        return [], [(cfg["name"], alert)] if alert else []

    all_jobs = scraper.fetch_jobs()

    if show_all:
        _print_job_table(all_jobs, f"ALL OPEN POSITIONS — {cfg['name']}")

    matched = apply_filters(all_jobs, LOCATION_FILTERS, TITLE_FILTERS)
    matched = [score_job(j) for j in matched]
    logger.info(
        "[%s] %d total open | %d passed filters",
        cfg["name"], len(all_jobs), len(matched),
    )
    return matched, []


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run(show_all: bool = False) -> list[Job]:
    job_cache.load()

    all_matched: list[Job] = []
    generic_alerts: list[tuple[str, str]] = []

    print(f"\n{'='*70}")
    print("  BIOPHARMA JOB SCRAPER")
    print(f"{'='*70}")
    print(f"  Location filters : {', '.join(LOCATION_FILTERS)}")
    print(f"  Title filters    : {', '.join(TITLE_FILTERS)}")
    print(f"{'='*70}\n")

    # ── Split companies by scraping constraint ────────────────────────────
    # Workday tenants share Cloudflare IP-level rate limiting — they MUST run
    # sequentially with 10-15 s gaps between cold sessions.
    # Every other ATS (Greenhouse, Workable, Paylocity, SuccessFactors, Generic)
    # hits independent domains and can run fully in parallel.
    workday_cfgs = [c for c in COMPANIES if c["ats"] == "workday"]
    other_cfgs   = [c for c in COMPANIES if c["ats"] != "workday"]

    # ── Launch non-Workday scrapers in a thread pool ──────────────────────
    # They start immediately and run overlapped with the Workday loop below.
    pool = ThreadPoolExecutor(max_workers=_OTHER_WORKERS, thread_name_prefix="scraper")
    other_futures = {pool.submit(_scrape_one, cfg, show_all): cfg for cfg in other_cfgs}

    # ── Workday: sequential with mandatory inter-company delays ───────────
    for idx, cfg in enumerate(workday_cfgs):
        matched, alerts = _scrape_one(cfg, show_all)
        all_matched.extend(matched)
        generic_alerts.extend(alerts)

        if idx < len(workday_cfgs) - 1:
            delay = random.uniform(10.0, 15.0)
            logger.info("Waiting %.1fs before next Workday company…", delay)
            time.sleep(delay)

    # ── Collect non-Workday results ───────────────────────────────────────
    pool.shutdown(wait=True)
    for future, cfg in other_futures.items():
        try:
            matched, alerts = future.result()
            all_matched.extend(matched)
            generic_alerts.extend(alerts)
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

    export_html(all_matched, generic_alerts, COMPANIES)

    # Persist cache — prune entries for jobs no longer in matched results
    # (filled / removed positions) to keep seen_jobs.json small.
    job_cache.prune_and_save({j.url for j in all_matched})

    return all_matched


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Biopharma job scraper")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print every open position (unfiltered) before showing scored matches",
    )
    args = parser.parse_args()
    run(show_all=args.all)
