"""
Tests for the fan-out and assembly layer.

What's protected here: one option's problem never takes down the others,
no option ever gets a guessed value, and the dimension regrouping doesn't
lose or alter anything the engine produced.
"""

import pytest

from decision_paths.change_major.comparison import (
    STATUS_CALCULATED,
    STATUS_FAILED,
    STATUS_PENDING,
    run_multi_comparison,
)
from decision_paths.change_major.comparison_inputs import (
    ComparisonOption,
    MultiComparisonInputs,
)
from decision_paths.change_major.engine import calculate


def _reference_data() -> dict:
    """Minimal institution data, same shape the loader produces."""

    def major(display, required, earnings_value):
        return {
            "display_name": display,
            "official_program_name": f"BS in {display}",
            "degree_type": "BS",
            "credits_required": required,
            "credits_required_source": "Test catalog",
            "credits_required_source_date": "2026-01-01",
            "earnings": {
                "1yr": {
                    "value": earnings_value,
                    "status": "available" if earnings_value else "unavailable",
                    "status_note": None if earnings_value else "No data reported",
                    "label": "Median earnings 1 year after graduation",
                    "graduates_measured": 100,
                },
                "4yr": {
                    "value": None, "status": "unavailable", "status_note": "n/a",
                    "label": "Median earnings 4 years after graduation",
                    "graduates_measured": None,
                },
                "5yr": {
                    "value": None, "status": "unavailable", "status_note": "n/a",
                    "label": "Median earnings 5 years after graduation",
                    "graduates_measured": None,
                },
                "cip_4_digit": "11.01",
                "cip_title": "Computer Science",
                "degrees_awarded_in_field": 200,
                "shared_note": None,
                "source": "College Scorecard",
                "source_url": None,
                "dataset_release": "2024",
                "retrieved": "2026-01-01",
                "credential_level_label": "Bachelor's",
                "population_note": "Federally aided graduates only.",
            },
            "occupations": {
                "list": [],
                "crosswalk_source": "CIP-SOC",
                "crosswalk_source_url": None,
                "crosswalk_limitation": "Relatedness is expert judgment.",
                "wage_source": "BLS OEWS",
                "wage_release": "2024",
                "projections_source": "BLS EP",
                "projections_cycle": "2024-2034",
                "retrieved": "2026-01-01",
            },
        }

    return {
        "institution": {
            "name": "Test University",
            "tuition": {
                "full_time_semester_estimate": 5000.0,
                "full_time_semester_estimate_source": "Test bursar",
                "full_time_semester_estimate_source_date": "2026-01-01",
                "full_time_credit_threshold": 12,
                "below_full_time_note": "Hourly below 12.",
            },
        },
        "majors": {
            "psychology": major("Psychology", 120, 30396),
            "computer_science": major("Computer Science", 120, 70235),
            "information_technology": major("Information Technology", 120, 70235),
            "mechanical_engineering": major("Mechanical Engineering", 128, 68000),
        },
        "credits_per_semester_full_time": 15,
    }


def _inputs(options) -> MultiComparisonInputs:
    return MultiComparisonInputs(
        current_major="psychology", credits_completed=72, options=options
    )


def test_one_request_produces_one_result_per_alternative():
    inputs = _inputs(
        [
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="information_technology", credits_transferable=69),
            ComparisonOption(major="mechanical_engineering", credits_transferable=54),
        ]
    )
    snapshot = run_multi_comparison(inputs, _reference_data(), calculate=calculate)

    assert len(snapshot.outcomes) == 3
    assert all(o.status == STATUS_CALCULATED for o in snapshot.outcomes)
    assert snapshot.anchor_display == "Psychology"


def test_each_option_is_calculated_against_its_own_transfer_figure():
    """The failure this catches: fan-out reusing one option's inputs for
    another, which would look completely plausible on screen."""
    inputs = _inputs(
        [
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="information_technology", credits_transferable=30),
        ]
    )
    snapshot = run_multi_comparison(inputs, _reference_data(), calculate=calculate)

    cs = snapshot.outcome_for("computer_science")
    it = snapshot.outcome_for("information_technology")

    cs_transfer = cs.dimensions["credits"]["credits_transferable"]["value"]
    it_transfer = it.dimensions["credits"]["credits_transferable"]["value"]
    assert cs_transfer == 66
    assert it_transfer == 30

    # Fewer transferred credits must mean more remaining, not the same.
    cs_remaining = cs.dimensions["timeline"]["credits_remaining_prospective"]["value"]
    it_remaining = it.dimensions["timeline"]["credits_remaining_prospective"]["value"]
    assert it_remaining > cs_remaining


def test_missing_transfer_figure_is_pending_not_calculated():
    inputs = _inputs(
        [
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="mechanical_engineering"),
        ]
    )
    snapshot = run_multi_comparison(inputs, _reference_data(), calculate=calculate)

    assert [o.major_key for o in snapshot.calculated()] == ["computer_science"]
    pending = snapshot.pending()
    assert [o.major_key for o in pending] == ["mechanical_engineering"]
    assert pending[0].missing_fields == ["credits_transferable"]
    # Crucially: no numbers were produced for it.
    assert pending[0].dimensions is None


def test_one_invalid_option_does_not_kill_the_comparison():
    inputs = _inputs(
        [
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="information_technology", credits_transferable=999),
        ]
    )
    snapshot = run_multi_comparison(inputs, _reference_data(), calculate=calculate)

    assert [o.major_key for o in snapshot.calculated()] == ["computer_science"]
    failed = snapshot.failed()
    assert [o.major_key for o in failed] == ["information_technology"]
    assert "cannot exceed" in failed[0].error


def test_unknown_major_fails_only_that_option():
    inputs = _inputs(
        [
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="basket_weaving", credits_transferable=10),
        ]
    )
    snapshot = run_multi_comparison(inputs, _reference_data(), calculate=calculate)

    assert len(snapshot.calculated()) == 1
    assert len(snapshot.failed()) == 1
    assert "basket_weaving" in snapshot.failed()[0].error


def test_assumptions_and_limitations_are_deduplicated():
    """Every pairwise run repeats the same tuition-model caveat. Stating it
    three times would read like three different warnings."""
    inputs = _inputs(
        [
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="information_technology", credits_transferable=69),
            ComparisonOption(major="mechanical_engineering", credits_transferable=54),
        ]
    )
    snapshot = run_multi_comparison(inputs, _reference_data(), calculate=calculate)

    assert len(snapshot.assumptions) == len(set(snapshot.assumptions))
    assert len(snapshot.limitations) == len(set(snapshot.limitations))
    assert snapshot.assumptions


def test_dimension_blocks_carry_source_and_status_through():
    """Regrouping must not strip provenance -- a value without its source
    can't render in the 'why am I seeing this' panel."""
    inputs = _inputs([ComparisonOption(major="computer_science", credits_transferable=66)])
    snapshot = run_multi_comparison(inputs, _reference_data(), calculate=calculate)

    tuition = snapshot.calculated()[0].dimensions["financial"]["incremental_tuition"]
    assert "source" in tuition and tuition["source"]
    assert "source_date" in tuition


def test_unavailable_earnings_stay_none_never_zero():
    data = _reference_data()
    data["majors"]["psychology"]["earnings"]["1yr"] = {
        "value": None,
        "status": "unavailable",
        "status_note": "No data reported",
        "label": "Median earnings 1 year after graduation",
        "graduates_measured": None,
    }
    inputs = _inputs([ComparisonOption(major="computer_science", credits_transferable=66)])
    snapshot = run_multi_comparison(inputs, data, calculate=calculate)

    career = snapshot.calculated()[0].dimensions["career"]
    assert career["annual_salary_delta"]["value"] is None
    assert career["annual_salary_delta"]["status"] == "unavailable"


def test_snapshot_dict_shape():
    inputs = _inputs([ComparisonOption(major="computer_science", credits_transferable=66)])
    snapshot = run_multi_comparison(inputs, _reference_data(), calculate=calculate)
    as_dict = snapshot.to_dict()

    assert as_dict["anchor"]["major"] == "Psychology"
    assert as_dict["credits_completed"] == 72
    assert as_dict["options"][0]["status"] == STATUS_CALCULATED
    assert "dimensions" in as_dict["options"][0]


def test_unknown_anchor_raises():
    inputs = MultiComparisonInputs(
        current_major="basket_weaving",
        credits_completed=72,
        options=[ComparisonOption(major="computer_science", credits_transferable=66)],
    )
    with pytest.raises(ValueError, match="Unknown current_major"):
        run_multi_comparison(inputs, _reference_data(), calculate=calculate)
