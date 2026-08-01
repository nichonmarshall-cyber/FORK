"""
Tests for the College Scorecard earnings join.

The theme here is that missing data has to stay missing. Federal earnings
data is suppressed for small programs, and the entire provenance design
falls apart the moment a suppressed figure gets quietly rendered as 0 or
silently swapped for a national average. These tests exist to make that
failure mode loud.
"""

import pytest

from decision_paths.change_major.engine import calculate
from decision_paths.change_major.inputs import ChangeMajorInputs

from ..loader import build_reference_data


@pytest.fixture
def reference_data():
    return build_reference_data("unt")


def test_real_scorecard_values_are_loaded(reference_data):
    """Locks in the actual figures from the June 2026 federal release, so a
    bad re-import or a hand-edit shows up as a test failure rather than as
    a wrong number in front of a student."""
    cs = reference_data["majors"]["computer_science"]["earnings"]
    assert cs["1yr"]["value"] == 70235.0
    assert cs["4yr"]["value"] == 104024.0
    assert cs["5yr"]["value"] == 102134.0
    assert cs["cip_4_digit"] == "11.01"

    psych = reference_data["majors"]["psychology_ba"]["earnings"]
    assert psych["1yr"]["value"] == 30396.0
    assert psych["cip_4_digit"] == "42.01"


def test_cs_and_it_share_one_federal_category(reference_data):
    """UNT reports both programs under a single federal category, so the
    Scorecard genuinely cannot separate them. Same numbers is correct — but
    only if the response says so."""
    cs = reference_data["majors"]["computer_science"]["earnings"]
    it = reference_data["majors"]["information_technology"]["earnings"]

    assert cs["1yr"]["value"] == it["1yr"]["value"]
    assert cs["cip_4_digit"] == it["cip_4_digit"] == "11.01"

    for block, name in ((cs, "Computer Science"), (it, "Information Technology")):
        assert block["shared_note"], f"{name} must explain the shared category"
        assert "broader group" in block["shared_note"]
        assert name in block["shared_note"]


def test_psychology_ba_and_bs_share_one_federal_category(reference_data):
    ba = reference_data["majors"]["psychology_ba"]["earnings"]
    bs = reference_data["majors"]["psychology_bs"]["earnings"]

    assert ba["1yr"]["value"] == bs["1yr"]["value"]
    assert ba["cip_4_digit"] == bs["cip_4_digit"]
    for block in (ba, bs):
        assert "B.A." in block["shared_note"] and "B.S." in block["shared_note"]


def test_information_technology_does_not_borrow_information_science(reference_data):
    """11.04 Information Science/Studies is a DIFFERENT UNT program. Using
    its earnings for Information Technology would be a plausible-looking
    wrong answer, which is the worst kind."""
    it = reference_data["majors"]["information_technology"]["earnings"]
    assert it["cip_4_digit"] != "11.04"
    assert it["1yr"]["value"] != 52449.0


def test_every_major_carries_the_population_caveat(reference_data):
    """Scorecard earnings only cover federal aid recipients who were
    working and not enrolled. That's a big limitation and it must travel
    with the data."""
    for key, major in reference_data["majors"].items():
        note = major["earnings"]["population_note"]
        assert note, key
        assert "federal financial aid" in note
        assert "not enrolled" in note


def test_suppressed_earnings_never_become_zero():
    """The core anti-invention guarantee, exercised against a synthetic
    suppressed program rather than waiting for the real data to change."""
    data = build_reference_data("unt")
    suppressed = {
        "value": None,
        "status": "privacy_suppressed",
        "status_note": "Too few graduates to publish.",
        "label": "Median earnings 1 year after graduation",
        "metric_code": "EARN_MDN_1YR",
        "graduates_measured": None,
    }
    data["majors"]["computer_science"]["earnings"]["1yr"] = suppressed

    result = calculate(
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="psychology_bs",
            credits_completed=72,
            credits_transferable=60,
        ),
        data,
    )

    # Not 0, not a guess, not a national average — absent, with a reason.
    assert result.foregone_earnings_cost.value is None
    assert result.foregone_earnings_cost.status == "privacy_suppressed"
    assert result.annual_salary_delta.value is None

    # And the total must admit it's incomplete rather than passing off a
    # tuition-only figure as the full comparison.
    assert result.incremental_total_cost.status == "partial"
    total_note = result.incremental_total_cost.status_note
    assert total_note is not None
    assert "tuition only" in total_note.lower()

    assert any("too few graduates" in lim.lower() for lim in result.limitations)


def test_delayed_income_uses_current_major_not_prospective(reference_data):
    """The question is what income you give up by graduating later, so the
    rate comes from the major you're leaving, not the one you're joining."""
    inputs = ChangeMajorInputs(
        current_major="computer_science",   # $70,235 at 1yr
        prospective_major="psychology_bs",  # $30,396 at 1yr
        credits_completed=72,
        credits_transferable=60,
    )
    result = calculate(inputs, reference_data)

    semesters = result.incremental_semesters.value
    delayed = result.foregone_earnings_cost.value
    assert semesters is not None and delayed is not None

    expected = round((semesters / 2) * 70235.0, 2)
    assert delayed == expected
    # Would be far lower if it had wrongly used psychology's figure.
    assert delayed > (semesters / 2) * 30396.0


def test_four_and_five_year_figures_are_context_only(reference_data):
    """They're shown to the student, but must never enter the math."""
    result = calculate(
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="psychology_bs",
            credits_completed=72,
            credits_transferable=60,
        ),
        reference_data,
    )
    semesters = result.incremental_semesters.value
    delayed = result.foregone_earnings_cost.value
    assert semesters is not None and delayed is not None

    for later in (104024.0, 102134.0):  # CS 4yr and 5yr
        assert delayed != round((semesters / 2) * later, 2)

    context = {c["major"]: c for c in result.earnings_context}
    trajectory = context["Computer Science"]["trajectory"]
    assert [t["value"] for t in trajectory] == [70235.0, 104024.0, 102134.0]


def test_graduate_count_is_labelled_as_the_broader_field(reference_data):
    """371 degrees is the whole federal category, not the CS program. The
    label has to say that, or it reads as a precise program-level count."""
    result = calculate(
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="psychology_bs",
            credits_completed=72,
            credits_transferable=60,
        ),
        reference_data,
    )
    ctx = result.earnings_context[0]
    assert ctx["degrees_awarded_label"] == "Degrees awarded in this broader field"
    assert ctx["degrees_awarded_in_field"] == 371


def test_cip_codes_stay_out_of_student_facing_labels(reference_data):
    """CIP codes belong in provenance detail, not in a label someone
    reading the result has to decode."""
    result = calculate(
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="psychology_bs",
            credits_completed=72,
            credits_transferable=60,
        ),
        reference_data,
    )
    for item in (
        result.foregone_earnings_cost,
        result.current_major_median_salary,
        result.annual_salary_delta,
        result.incremental_total_cost,
    ):
        assert "11.01" not in item.label
        assert "CIP" not in item.label
        assert "EARN_MDN" not in item.label

    # But it IS present in the provenance, for anyone checking the work.
    assert "11.01" in result.current_major_median_salary.source


def test_delayed_income_is_not_called_a_guaranteed_loss(reference_data):
    result = calculate(
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="psychology_bs",
            credits_completed=72,
            credits_transferable=60,
        ),
        reference_data,
    )
    label = result.foregone_earnings_cost.label
    assert label == "Estimated early-career income delayed"
    for banned in ("lost income", "lost salary", "guaranteed"):
        assert banned not in label.lower()