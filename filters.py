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

def matches_location(job: Job, location_terms: list[str]) -> bool:
    """Check location; *location_terms* must already be lowercased by the caller."""
    loc = job.location.lower()
    return any(term in loc for term in location_terms)


def matches_title(job: Job, title_terms: list[str]) -> bool:
    """Check title; *title_terms* must already be lowercased by the caller."""
    title = job.title.lower()
    return any(term in title for term in title_terms)


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
    matched_loc = next((t for t in SCORE_LOCATION_POSITIVE if t in loc), None)
    if matched_loc:
        job.score += 4
        job.matched_keywords.add(f"location:{matched_loc}")
    elif not any(t in loc for t in SCORE_LOCATION_NEUTRAL):
        job.score -= 2
        job.deducted_keywords.add(f"location:{job.location}")

    return job
