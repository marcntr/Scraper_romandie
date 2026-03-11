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
# Hard exclusion filter (applied before location / title checks)
# ---------------------------------------------------------------------------

def _is_excluded_title(job: Job) -> bool:
    """Return True if the job title contains a seniority-mismatch pattern.

    These roles (VP, Head of, Senior Director, Principal) are hard-filtered
    rather than score-penalised because they represent a structural mismatch
    that no number of positive keywords can overcome.
    """
    return any(
        re.search(pat, job.title, re.IGNORECASE)
        for pat in EXCLUDE_TITLE_PATTERNS
    )


# ---------------------------------------------------------------------------
# Location / title substring matchers
# ---------------------------------------------------------------------------

def matches_location(job: Job, location_terms: list[str]) -> bool:
    loc = job.location.lower()
    return any(term.lower() in loc for term in location_terms)


def matches_title(job: Job, title_terms: list[str]) -> bool:
    title = job.title.lower()
    return any(term.lower() in title for term in title_terms)


# ---------------------------------------------------------------------------
# Combined filter pipeline
# ---------------------------------------------------------------------------

def apply_filters(
    jobs: list[Job],
    location_terms: list[str],
    title_terms: list[str],
) -> list[Job]:
    return [
        j for j in jobs
        if not _is_excluded_title(j)
        and matches_location(j, location_terms)
        and matches_title(j, title_terms)
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
    for term in SCORE_POSITIVE:
        if term.lower() in corpus_lower:
            if term not in job.matched_keywords:
                job.matched_keywords.append(term)
                job.score += 1

    # -- Negative phrases: -2 per unique phrase found in description --------
    for phrase in SCORE_NEGATIVE_PHRASES:
        if phrase.lower() in desc_lower:
            if phrase not in job.deducted_keywords:
                job.deducted_keywords.append(phrase)
                job.score -= 2

    # -- Negative regex patterns: -2 per pattern match in description -------
    for pattern in SCORE_NEGATIVE_REGEX:
        match = re.search(pattern, job.description, re.IGNORECASE)
        if match:
            snippet = match.group(0)
            if snippet not in job.deducted_keywords:
                job.deducted_keywords.append(snippet)
                job.score -= 2

    # -- Geographic bonus: +4 Romandie, 0 major hubs, -2 elsewhere ----------
    loc = job.location.lower()
    matched_loc = next((t for t in SCORE_LOCATION_POSITIVE if t in loc), None)
    if matched_loc:
        job.score += 4
        job.matched_keywords.append(f"location:{matched_loc}")
    elif not any(t in loc for t in SCORE_LOCATION_NEUTRAL):
        job.score -= 2
        job.deducted_keywords.append(f"location:{job.location}")

    return job
