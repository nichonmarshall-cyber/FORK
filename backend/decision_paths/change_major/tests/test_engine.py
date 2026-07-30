import json
import os

import pytest

from ..engine import calculate
from ..inputs import ChangeMajorInputs

REFERENCE_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data_sources", "change_major_reference.json"
)


@pytest.fixture
def reference_data():
    with open(REFERENCE_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_switching_cs_to_it_reports_incremental_not_gross_cost(reference_data):
    """Golden values against the current placeholder data.

    These are differences, not totals. Finishing CS from 72 credits means
    paying for 48 more; finishing IT from 60 transferred credits means 60
    more. The real cost is that 12-credit gap. Charging the full 60 would
    overstate switching by roughly 5x, which is the regression this test
    exists to catch.
    """
    inputs = ChangeMajorInputs(
        current_major="computer_science",
        prospective_major="information_technology",
        credits_completed=72,
        credits_transferable=60,
    )
    result = calculate(inputs, reference_data)

    assert result.credits_lost.value == 12

    # Staying: 120 - 72 = 48 credits -> 3.2 semesters -> $14,400
    assert result.current_path.credits_remaining.value == 48
    assert result.current_path.semesters_remaining.value == 3.2
    assert result.current_path.tuition_remaining.value == 14400.0

    # Switching: 120 - 60 = 60 credits -> 4.0 semesters -> $18,000
    assert result.prospective_path.credits_remaining.value == 60
    assert result.prospective_path.semesters_remaining.value == 4.0
    assert result.prospective_path.tuition_remaining.value == 18000.0

    # The difference is what switching costs.
    assert result.incremental_semesters.value == 0.8
    assert result.incremental_tuition.value == 3600.0
    # 0.8 extra semesters = 0.4 years * $62,000 IT median = $24,800
    assert result.foregone_earnings_cost.value == 24800.0
    assert result.incremental_total_cost.value == 28400.0

    # CS $75,000 -> IT $62,000
    assert result.annual_salary_delta.value == -13000


def test_switching_can_be_cheaper_and_reports_a_negative(reference_data):
    """A shorter target degree makes switching a net saving, so this has to
    come back negative. Clamping to zero would hide a saving, which is as
    misleading as hiding a cost."""
    inputs = ChangeMajorInputs(
        current_major="nursing",              # requires 128
        prospective_major="psychology",       # requires 120
        credits_completed=60,
        credits_transferable=60,
    )
    result = calculate(inputs, reference_data)

    assert result.incremental_semesters.value == -0.53
    assert result.incremental_tuition.value == -2400.0
    assert result.foregone_earnings_cost.value == -12000.0
    assert result.incremental_total_cost.value == -14400.0


def test_zero_transfer_credits_maximizes_incremental_cost(reference_data):
    inputs = ChangeMajorInputs(
        current_major="psychology",
        prospective_major="mechanical_engineering",
        credits_completed=90,
        credits_transferable=0,
    )
    result = calculate(inputs, reference_data)

    assert result.credits_lost.value == 90
    # Staying: 120 - 90 = 30 -> 2.0 semesters
    assert result.current_path.semesters_remaining.value == 2.0
    # Switching: 128 - 0 = 128 -> 8.53 semesters
    assert result.prospective_path.semesters_remaining.value == pytest.approx(8.53, abs=0.01)
    assert result.incremental_semesters.value == pytest.approx(6.53, abs=0.01)
    assert result.incremental_tuition.value == 29400.0


def test_both_paths_complete_means_no_difference(reference_data):
    inputs = ChangeMajorInputs(
        current_major="business_administration",
        prospective_major="psychology",
        credits_completed=120,
        credits_transferable=120,
    )
    result = calculate(inputs, reference_data)

    assert result.current_path.credits_remaining.value == 0
    assert result.prospective_path.credits_remaining.value == 0
    assert result.incremental_semesters.value == 0.0
    assert result.incremental_tuition.value == 0.0
    assert result.incremental_total_cost.value == 0.0


def test_audit_derived_credits_required_overrides_reference_table(reference_data):
    """An audit is more reliable than the hand-entered table, so it takes
    precedence, and it carries its own citation rather than borrowing the
    table's."""
    inputs = ChangeMajorInputs(
        current_major="computer_science",
        prospective_major="information_technology",
        credits_completed=72,
        credits_transferable=60,
        prospective_credits_required=132,
        prospective_credits_required_source="UNT what-if degree audit, run 2026-07-29",
    )
    result = calculate(inputs, reference_data)

    assert result.prospective_path.credits_required.value == 132
    assert "what-if degree audit" in result.prospective_path.credits_required.source
    # 132 - 60 = 72 remaining, vs 48 staying -> 24 credit difference
    assert result.prospective_path.credits_remaining.value == 72
    assert result.incremental_tuition.value == 7200.0


def test_credit_provenance_flows_from_inputs_into_result(reference_data):
    """The result has to distinguish a registrar's figure from a student's
    estimate. If both showed the same source, the provenance panel would be
    inaccurate."""
    inputs = ChangeMajorInputs(
        current_major="computer_science",
        prospective_major="information_technology",
        credits_completed=33,
        credits_transferable=20,
        credits_source="UNT degree audit, parsed 2026-07-29",
        credits_transferable_source="Advisor estimate",
        credits_source_date="2026-07-29",
    )
    result = calculate(inputs, reference_data)

    assert result.current_path.credits_counted.source == "UNT degree audit, parsed 2026-07-29"
    assert result.prospective_path.credits_counted.source == "Advisor estimate"
    assert result.current_path.credits_counted.source_date == "2026-07-29"
    assert any("degree audit" in a for a in result.assumptions)


def test_every_line_item_carries_provenance(reference_data):
    """Every value out of the engine needs a source. This test is what
    guarantees the "Why am I seeing this?" panel has something behind it."""
    inputs = ChangeMajorInputs(
        current_major="nursing",
        prospective_major="business_administration",
        credits_completed=64,
        credits_transferable=40,
    )
    result = calculate(inputs, reference_data)

    top_level = [
        result.credits_lost,
        result.incremental_semesters,
        result.incremental_tuition,
        result.foregone_earnings_cost,
        result.incremental_total_cost,
        result.current_major_median_salary,
        result.prospective_major_median_salary,
        result.annual_salary_delta,
    ]
    per_path = [
        li
        for path in (result.current_path, result.prospective_path)
        for li in (
            path.credits_required,
            path.credits_counted,
            path.credits_remaining,
            path.semesters_remaining,
            path.tuition_remaining,
        )
    ]

    for line_item in top_level + per_path:
        assert line_item.source, f"{line_item.label} is missing a source"
        assert line_item.source_date, f"{line_item.label} is missing a source_date"

    assert len(result.assumptions) > 0
    assert len(result.limitations) > 0


def test_unknown_major_key_raises_instead_of_guessing(reference_data):
    inputs = ChangeMajorInputs(
        current_major="computer_science",
        prospective_major="underwater_basket_weaving",
        credits_completed=60,
        credits_transferable=30,
    )
    with pytest.raises(ValueError, match="Unknown prospective_major"):
        calculate(inputs, reference_data)


def test_same_major_twice_rejected_at_validation(reference_data):
    """The engine used to be the only thing catching this. Now inputs.py
    rejects it first, so it never reaches the engine."""
    with pytest.raises(ValueError, match="must differ"):
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="computer_science",
            credits_completed=60,
            credits_transferable=60,
        )


def test_transferable_credits_cannot_exceed_completed():
    with pytest.raises(Exception):
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="information_technology",
            credits_completed=30,
            credits_transferable=45,
        )


def test_negative_credits_completed_rejected():
    with pytest.raises(Exception):
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="information_technology",
            credits_completed=-5,
            credits_transferable=0,
        )


def test_audit_override_without_source_is_rejected():
    """An override with no citation would render as an authoritative figure
    with nothing behind it."""
    with pytest.raises(Exception, match="source is required"):
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="information_technology",
            credits_completed=72,
            credits_transferable=60,
            prospective_credits_required=132,
        )


def test_credit_requirements_cite_catalog_not_salary_dataset(reference_data):
    """Credit requirements come from the course catalog; salaries come from
    College Scorecard. There was a bug where credit figures cited the salary
    source, which is worse than no citation at all, since a wrong citation
    still looks trustworthy."""
    inputs = ChangeMajorInputs(
        current_major="computer_science",
        prospective_major="information_technology",
        credits_completed=60,
        credits_transferable=50,
    )
    result = calculate(inputs, reference_data)

    assert "catalog" in result.current_path.credits_required.source.lower()
    assert "catalog" in result.prospective_path.credits_required.source.lower()
    assert "scorecard" in result.current_major_median_salary.source.lower()
    assert "scorecard" in result.prospective_major_median_salary.source.lower()
    assert "scorecard" in result.foregone_earnings_cost.source.lower()
