"""Tests for filters.py — the location/title/score pipeline.

Run with:  python -m unittest discover -s tests

Focused on the class of bug that caused real false negatives: ATS platforms
(Workday, SuccessFactors, ...) that render a Swiss location as a bare ISO
country code ("Boudry - CH", "Vevey, CH") rather than a spelled-out city or
"Switzerland". See filters.location_text_matches / _SWISS_COUNTRY_CODE_RE.
"""

import unittest

from config import LOCATION_FILTERS, TITLE_FILTERS
from filters import (
    apply_filters,
    explain_job,
    location_text_matches,
    matches_location,
    matches_title,
    score_job,
    title_text_matches,
)
from models import Job


def _make_job(title="Scientist", location="Geneva, Switzerland", description="") -> Job:
    return Job(
        title=title,
        company="TestCo",
        location=location,
        url=f"https://example.com/{title}",
        shortcode="",
        department="",
        posted_date="",
        description=description,
    )


class LocationTextMatchesTests(unittest.TestCase):
    """The core regression suite for the Boudry/BMS false-negative bug."""

    def test_spelled_out_country_and_city_names_match(self):
        for loc in [
            "Geneva, Switzerland",
            "Lausanne, Vaud, Switzerland",
            "Zurich, Switzerland",
            "Basel-Stadt, Schweiz",
            "Some Office, Suisse",
        ]:
            with self.subTest(loc=loc):
                self.assertTrue(location_text_matches(loc, LOCATION_FILTERS))

    def test_bare_ch_country_code_matches(self):
        # Workday renders "<City> - CH"; SuccessFactors renders "<City>, CH".
        # Neither spells out a recognised city or "Switzerland".
        for loc in ["Boudry - CH", "Vevey, CH", "Zug - CH", "Nyon, CH", "Visp - CH"]:
            with self.subTest(loc=loc):
                self.assertTrue(location_text_matches(loc, LOCATION_FILTERS))

    def test_non_swiss_locations_starting_with_ch_do_not_match(self):
        # Regression guard: a naive substring match on "ch" would wrongly
        # accept any of these.
        for loc in [
            "Chicago, IL, USA",
            "Shanghai, China",
            "Santiago, Chile",
            "N'Djamena, Chad",
            "Munich, Germany",
            "Christmas Island",
        ]:
            with self.subTest(loc=loc):
                self.assertFalse(location_text_matches(loc, LOCATION_FILTERS))

    def test_unrelated_location_does_not_match(self):
        self.assertFalse(location_text_matches("Remote - USA", LOCATION_FILTERS))

    def test_matches_location_wraps_location_text_matches(self):
        job = _make_job(location="Boudry - CH")
        self.assertTrue(matches_location(job, LOCATION_FILTERS))


class TitleTextMatchesTests(unittest.TestCase):

    def test_known_term_matches(self):
        self.assertTrue(title_text_matches("Senior Scientist, Immunology", TITLE_FILTERS))

    def test_unrelated_title_does_not_match(self):
        self.assertFalse(title_text_matches("Warehouse Associate", TITLE_FILTERS))

    def test_matches_title_wraps_title_text_matches(self):
        job = _make_job(title="Senior Scientist, Immunology")
        self.assertTrue(matches_title(job, TITLE_FILTERS))


class ApplyFiltersTests(unittest.TestCase):

    def test_bms_boudry_scientist_job_survives_the_full_pipeline(self):
        # This is the exact job from the false-negative report: title and
        # location both plausible matches, but location is a bare "CH" code.
        job = _make_job(
            title="Scientist, Validation & Investigations",
            location="Boudry - CH",
        )
        self.assertEqual(apply_filters([job], LOCATION_FILTERS, TITLE_FILTERS), [job])

    def test_hard_exclusion_overrides_otherwise_matching_title_and_location(self):
        # Seniority-mismatch titles are dropped even when location/title
        # substrings would otherwise pass.
        for title in [
            "VP, Regulatory Affairs",
            "Head of Clinical Development",
            "Senior Director, Medical Affairs",
            "Drug Discovery Scientist (Machine Learning)",
        ]:
            with self.subTest(title=title):
                job = _make_job(title=title, location="Geneva, Switzerland")
                self.assertEqual(apply_filters([job], LOCATION_FILTERS, TITLE_FILTERS), [])

    def test_location_mismatch_is_dropped(self):
        job = _make_job(title="Scientist", location="Remote - USA")
        self.assertEqual(apply_filters([job], LOCATION_FILTERS, TITLE_FILTERS), [])

    def test_title_mismatch_is_dropped(self):
        job = _make_job(title="Warehouse Associate", location="Geneva, Switzerland")
        self.assertEqual(apply_filters([job], LOCATION_FILTERS, TITLE_FILTERS), [])


class ExplainJobTests(unittest.TestCase):

    def test_passing_job_explained_as_passed(self):
        job = _make_job(title="Scientist, Validation & Investigations", location="Boudry - CH")
        self.assertTrue(
            explain_job(job, LOCATION_FILTERS, TITLE_FILTERS).startswith("PASSED")
        )

    def test_hard_exclusion_reason_is_named(self):
        job = _make_job(title="VP, Regulatory Affairs", location="Geneva, Switzerland")
        reason = explain_job(job, LOCATION_FILTERS, TITLE_FILTERS)
        self.assertIn("hard-exclusion", reason)

    def test_location_only_rejection_is_named(self):
        job = _make_job(title="Scientist", location="Remote - USA")
        reason = explain_job(job, LOCATION_FILTERS, TITLE_FILTERS)
        self.assertIn("REJECTED at location", reason)
        self.assertNotIn("title", reason.split("—")[0])

    def test_title_only_rejection_is_named(self):
        job = _make_job(title="Warehouse Associate", location="Geneva, Switzerland")
        reason = explain_job(job, LOCATION_FILTERS, TITLE_FILTERS)
        self.assertIn("REJECTED at title", reason)


class ScoreJobTests(unittest.TestCase):

    def test_positive_keyword_counted_once_even_if_repeated(self):
        job = _make_job(description="immunology immunology immunology")
        score_job(job)
        self.assertEqual(job.score, job.score)  # sanity: no crash
        self.assertIn("immunology", job.matched_keywords)
        # +1 for "immunology" matched once regardless of repetition, plus
        # the geographic bonus for the default Geneva location (+4).
        self.assertEqual(job.score, 1 + 4)

    def test_negative_phrase_applies_once(self):
        job = _make_job(description="Requires clinical operations experience.")
        score_job(job)
        self.assertIn("clinical operations", job.deducted_keywords)

    def test_negative_regex_applies(self):
        job = _make_job(description="Minimum 3 years of clinical research experience required.")
        score_job(job)
        self.assertTrue(any("clinical research" in kw for kw in job.deducted_keywords))

    def test_romandie_location_gets_positive_bonus(self):
        job = _make_job(location="Lausanne, Switzerland")
        score_job(job)
        self.assertEqual(job.score, 4)

    def test_neutral_hub_location_gets_no_bonus(self):
        job = _make_job(location="Zurich, Switzerland")
        score_job(job)
        self.assertEqual(job.score, 0)

    def test_unrecognised_location_gets_penalty(self):
        # "remote" is deliberately in SCORE_LOCATION_POSITIVE (remote Swiss
        # roles score like Romandie), so use a location with no match at all.
        job = _make_job(location="Austin, TX, USA")
        score_job(job)
        self.assertEqual(job.score, -2)

    def test_boudry_is_recognised_as_romandie(self):
        # Boudry (BMS manufacturing site, Neuchâtel canton) only appears as
        # a bare "CH" code in Workday's locationsText, so it must be listed
        # explicitly in SCORE_LOCATION_POSITIVE to get the Romandie bonus.
        job = _make_job(location="Boudry - CH")
        score_job(job)
        self.assertEqual(job.score, 4)


if __name__ == "__main__":
    unittest.main()
