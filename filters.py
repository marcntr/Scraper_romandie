"""Filtering and scoring pipeline.

Order of operations applied in ``apply_filters()``:
  1. Hard exclusion — drop seniority-mismatch titles (VP, Head of, etc.)
  2. Location match — substring check against LOCATION_FILTERS
  3. Title match   — substring check against TITLE_FILTERS

``score_job()`` is called *after* filtering and mutates the Job in-place:
  - +1 per unique positive keyword found (in title + description combined)
  - -2 per unique negative phrase found (in description only)
  - -2 per unique negative regex pattern matched (in description only)
  - +4 / 0 / -2 geographic bonus based on job.location (Romandie / major hub / elsewhere)
"""

import re

from config import (
    EXCLUDE_TITLE_PATTERNS,
    SCORE_POSITIVE,
    SCORE_NEGATIVE_PHRASES,
    SCORE_NEGATIVE_REGEX,
    SCORE_LOCATION_POSITIVE,
    SCORE_LOCATION_NEUTRAL,
)
from models import Job


# ---------------------------------------------------------------------------
# Pre-compiled / pre-lowered constants — computed once at import time
# ---------------------------------------------------------------------------

# Hard-exclusion patterns compiled for reuse across all calls.
_EXCL_PATTERNS: list[re.Pattern] = [
    re.compile(pat, re.IGNORECASE) for pat in EXCLUDE_TITLE_PATTERNS
]

# Negative regex patterns compiled for reuse across all calls.
_NEG_PATTERNS: list[re.Pattern] = [
    re.compile(pat, re.IGNORECASE) for pat in SCORE_NEGATIVE_REGEX
]

# Pre-lowercased parallel lists avoid repeated .lower() inside tight loops.
_POS_TERMS_LOWER:   list[str] = [t.lower() for t in SCORE_POSITIVE]
_NEG_PHRASES_LOWER: list[str] = [p.lower() for p in SCORE_NEGATIVE_PHRASES]

# Many ATS platforms (Workday, SuccessFactors, ...) render Swiss locations as
# a bare ISO alpha-2 code with no city/country name LOCATION_FILTERS would
# otherwise catch, e.g. "Boudry - CH" or "Vevey, CH".  Match "ch" only as an
# isolated token (flanked by non-letters or string boundaries) so this never
# fires inside "Chicago", "China", "Chile", "Munich", etc.
_SWISS_COUNTRY_CODE_RE = re.compile(r"(?<![a-zA-Z])ch(?![a-zA-Z])", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Hard exclusion filter (applied before location / title checks)
# ---------------------------------------------------------------------------

def _is_excluded_title(job: Job) -> bool:
    """Return True if the job title contains a seniority-mismatch pattern.

    These roles (VP, Head of, Senior Director, Principal) are hard-filtered
    rather than score-penalised because they represent a structural mismatch
    that no number of positive keywords can overcome.
    """
    return any(pat.search(job.title) for pat in _EXCL_PATTERNS)


# ---------------------------------------------------------------------------
# Location / title substring matchers
# ---------------------------------------------------------------------------

def location_text_matches(location: str, location_terms: list[str]) -> bool:
    """True if ``location`` contains any term, or carries a standalone Swiss
    "CH" country-code token the term list would otherwise miss (see
    ``_SWISS_COUNTRY_CODE_RE`` above). Shared by the final filter pipeline
    and every scraper's Phase 1.5 pre-filter so both stages agree.
    """
    loc_lower = location.lower()
    if any(term.lower() in loc_lower for term in location_terms):
        return True
    return bool(_SWISS_COUNTRY_CODE_RE.search(location))


def matches_location(job: Job, location_terms: list[str]) -> bool:
    return location_text_matches(job.location, location_terms)


def title_text_matches(title: str, title_terms: list[str]) -> bool:
    title_lower = title.lower()
    return any(term.lower() in title_lower for term in title_terms)


def matches_title(job: Job, title_terms: list[str]) -> bool:
    return title_text_matches(job.title, title_terms)


# ---------------------------------------------------------------------------
# Combined filter pipeline
# ---------------------------------------------------------------------------

def apply_filters(
    jobs: list[Job],
    location_terms: list[str],
    title_terms: list[str],
) -> list[Job]:
    # Pre-lowercase once here rather than inside the per-job loop.
    loc_lower   = [t.lower() for t in location_terms]
    title_lower = [t.lower() for t in title_terms]
    return [
        j for j in jobs
        if not _is_excluded_title(j)
        and matches_location(j, loc_lower)
        and matches_title(j, title_lower)
    ]


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

def score_job(job: Job) -> Job:
    """Score a job in-place based on keyword relevance and location.

    Positive keywords (+1 each):
        Searched in ``job.title + job.description`` combined.  Each unique
        term is counted once regardless of how many times it appears.

    Negative phrases / patterns (-2 each):
        Searched in ``job.description`` only.  Title-level mentions of
        clinical requirements are unlikely and would be false positives.

    Geographic bonus (applied to job.location):
        +4  — Romandie / primary-target area (Geneva, Lausanne, Vaud, …)
         0  — Major Swiss hub outside target (Basel, Zurich, Bern, Zug)
        -2  — Anywhere else (unrecognised or non-target location)

    Returns the same ``Job`` object (mutated).
    """
    corpus = f"{job.title} {job.description}"
    corpus_lower = corpus.lower()
    desc_lower   = job.description.lower()

    # -- Positive keywords: +1 per unique term ------------------------------
    for term, term_lower in zip(SCORE_POSITIVE, _POS_TERMS_LOWER):
        if term_lower in corpus_lower:
            if term not in job.matched_keywords:
                job.matched_keywords.add(term)
                job.score += 1

    # -- Negative phrases: -2 per unique phrase found in description --------
    for phrase, phrase_lower in zip(SCORE_NEGATIVE_PHRASES, _NEG_PHRASES_LOWER):
        if phrase_lower in desc_lower:
            if phrase not in job.deducted_keywords:
                job.deducted_keywords.add(phrase)
                job.score -= 2

    # -- Negative regex patterns: -2 per pattern match in description -------
    for pat in _NEG_PATTERNS:
        match = pat.search(job.description)
        if match:
            snippet = match.group(0)
            if snippet not in job.deducted_keywords:
                job.deducted_keywords.add(snippet)
                job.score -= 2

    # -- Geographic bonus: +4 Romandie, 0 major hubs, -2 elsewhere ----------
    loc = job.location.lower()
    matched_loc = next((t for t in SCORE_LOCATION_POSITIVE if t.lower() in loc), None)
    if matched_loc:
        job.score += 4
        job.matched_keywords.add(f"location:{matched_loc}")
    elif not any(t.lower() in loc for t in SCORE_LOCATION_NEUTRAL):
        job.score -= 2
        job.deducted_keywords.add(f"location:{job.location}")

    return job


# ---------------------------------------------------------------------------
# Diagnostics — explain why a specific job would or wouldn't survive
# apply_filters(), without having to trace the three-stage pipeline by hand.
# ---------------------------------------------------------------------------

def explain_job(job: Job, location_terms: list[str], title_terms: list[str]) -> str:
    """Return a one-line human-readable verdict for ``job`` against the
    current filter configuration, naming the exact stage that would
    reject it. Used by ``main.py --explain`` for debugging false negatives.
    """
    if _is_excluded_title(job):
        pat = next(p.pattern for p in _EXCL_PATTERNS if p.search(job.title))
        return f"REJECTED at hard-exclusion — title matched pattern {pat!r}"

    loc_ok = matches_location(job, location_terms)
    title_ok = matches_title(job, title_terms)

    if not loc_ok and not title_ok:
        return (
            f"REJECTED at location+title — location {job.location!r} matched no "
            f"LOCATION_FILTERS term, and title {job.title!r} matched no TITLE_FILTERS term"
        )
    if not loc_ok:
        return f"REJECTED at location — {job.location!r} matched no LOCATION_FILTERS term"
    if not title_ok:
        return f"REJECTED at title — {job.title!r} matched no TITLE_FILTERS term"
    return "PASSED — matches location and title filters"
