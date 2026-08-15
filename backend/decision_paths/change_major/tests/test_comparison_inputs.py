"""
Tests for the multi-option input contract.

The behaviors worth protecting here are the ones that would silently put a
wrong number in front of a student: transfer credits bleeding across
options, a duplicate quietly overwriting a real value, or an incomplete
option getting calculated with a guess in place of a missing field.
"""

import pytest
from pydantic import ValidationError

from decision_paths.change_major.comparison_inputs import (
    ComparisonOption,
    DuplicateOptionError,
    MultiComparisonInputs,
)


def _inputs(**overrides) -> MultiComparisonInputs:
    """A complete three-option comparison, the shape most tests start from."""
    defaults = dict(
        current_major="psychology",
        credits_completed=72,
        options=[
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="information_technology", credits_transferable=69),
            ComparisonOption(major="mechanical_engineering", credits_transferable=54),
        ],
    )
    defaults.update(overrides)
    return MultiComparisonInputs(**defaults)


# --- transferable credits are per option --------------------------------


def test_each_option_keeps_its_own_transferable_figure():
    inputs = _inputs()
    assert inputs.option_for("computer_science").credits_transferable == 66
    assert inputs.option_for("information_technology").credits_transferable == 69
    assert inputs.option_for("mechanical_engineering").credits_transferable == 54


def test_pairwise_inputs_carry_that_option_s_own_figure():
    """The bug this guards against: one option's transfer number leaking
    into another option's calculation."""
    inputs = _inputs()
    for major, expected in [
        ("computer_science", 66),
        ("information_technology", 69),
        ("mechanical_engineering", 54),
    ]:
        pairwise = inputs.to_pairwise_inputs(inputs.option_for(major))
        assert pairwise.prospective_major == major
        assert pairwise.credits_transferable == expected
        assert pairwise.credits_completed == 72
        assert pairwise.current_major == "psychology"


def test_shared_provenance_flows_to_every_pairwise_input():
    inputs = _inputs(
        credits_source="Degree audit, parsed 2026-08-13",
        credits_source_date="2026-08-13",
    )
    for option in inputs.options:
        pairwise = inputs.to_pairwise_inputs(option)
        assert pairwise.credits_source == "Degree audit, parsed 2026-08-13"
        assert pairwise.credits_source_date == "2026-08-13"


def test_per_option_transfer_source_is_not_shared():
    """Two options can have transfer figures from different places — one
    from an audit, one the student guessed — and each result needs to say
    which one it was."""
    inputs = _inputs(
        options=[
            ComparisonOption(
                major="computer_science",
                credits_transferable=66,
                credits_transferable_source="What-if audit, 2026-08-01",
            ),
            ComparisonOption(major="information_technology", credits_transferable=69),
        ]
    )
    cs = inputs.to_pairwise_inputs(inputs.option_for("computer_science"))
    it = inputs.to_pairwise_inputs(inputs.option_for("information_technology"))
    assert cs.credits_transferable_source == "What-if audit, 2026-08-01"
    assert it.credits_transferable_source == "Student-reported"


# --- completeness: missing is pending, never guessed --------------------


def test_option_without_transferable_credits_is_incomplete():
    option = ComparisonOption(major="mechanical_engineering")
    assert not option.is_complete
    assert option.missing_fields() == ["credits_transferable"]


def test_zero_transferable_is_complete_not_missing():
    """Zero is a real answer — none of your credits apply. It must not be
    confused with 'we don't know yet'."""
    option = ComparisonOption(major="nursing", credits_transferable=0)
    assert option.is_complete
    assert option.missing_fields() == []


def test_partial_comparison_splits_ready_from_pending():
    inputs = _inputs(
        options=[
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="information_technology", credits_transferable=69),
            ComparisonOption(major="mechanical_engineering"),  # no figure yet
        ]
    )
    assert [o.major for o in inputs.ready_options()] == [
        "computer_science",
        "information_technology",
    ]
    assert [o.major for o in inputs.pending_options()] == ["mechanical_engineering"]


def test_incomplete_option_cannot_be_turned_into_pairwise_inputs():
    inputs = _inputs(
        options=[
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="mechanical_engineering"),
        ]
    )
    pending = inputs.option_for("mechanical_engineering")
    with pytest.raises(ValueError, match="credits_transferable"):
        inputs.to_pairwise_inputs(pending)


# --- the anchor -----------------------------------------------------------


def test_current_major_listed_as_an_option_is_treated_as_the_anchor():
    """"Compare Psychology, CS, and IT" from a Psychology major is normal
    phrasing. Psychology stays in the comparison as the baseline; it just
    isn't an alternative."""
    inputs = _inputs(
        options=[
            ComparisonOption(major="psychology", credits_transferable=72),
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="information_technology", credits_transferable=69),
        ]
    )
    assert [o.major for o in inputs.options] == [
        "computer_science",
        "information_technology",
    ]
    assert inputs.all_majors() == [
        "psychology",
        "computer_science",
        "information_technology",
    ]


def test_comparison_against_only_yourself_is_rejected():
    with pytest.raises(ValidationError, match="at least one alternative"):
        MultiComparisonInputs(
            current_major="psychology",
            credits_completed=72,
            options=[ComparisonOption(major="psychology", credits_transferable=72)],
        )


def test_empty_option_list_is_rejected():
    with pytest.raises(ValidationError, match="at least one alternative"):
        MultiComparisonInputs(
            current_major="psychology", credits_completed=72, options=[]
        )


# --- duplicates -----------------------------------------------------------


def test_identical_duplicate_collapses():
    inputs = _inputs(
        options=[
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="information_technology", credits_transferable=69),
            ComparisonOption(major="computer_science", credits_transferable=66),
        ]
    )
    assert [o.major for o in inputs.options] == [
        "computer_science",
        "information_technology",
    ]


def test_conflicting_duplicate_raises_rather_than_picking_one():
    with pytest.raises(ValidationError, match="given twice with different values"):
        MultiComparisonInputs(
            current_major="psychology",
            credits_completed=72,
            options=[
                ComparisonOption(major="computer_science", credits_transferable=66),
                ComparisonOption(major="computer_science", credits_transferable=40),
            ],
        )


# --- validation deferred to the existing pairwise contract ---------------


def test_transferable_exceeding_completed_fails_at_the_pairwise_boundary():
    """The rule lives in inputs.py and stays there. What matters is that
    it still fires, and that it fires per option so the service can mark
    one option failed instead of losing the whole comparison."""
    inputs = _inputs(
        options=[
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="information_technology", credits_transferable=99),
        ],
        credits_completed=72,
    )
    good = inputs.to_pairwise_inputs(inputs.option_for("computer_science"))
    assert good.credits_transferable == 66

    with pytest.raises(ValidationError, match="cannot exceed"):
        inputs.to_pairwise_inputs(inputs.option_for("information_technology"))


def test_credits_required_override_needs_a_source():
    with pytest.raises(ValidationError, match="source is required"):
        ComparisonOption(
            major="computer_science",
            credits_transferable=66,
            prospective_credits_required=120,
        )


def test_credits_required_override_flows_through_with_its_source():
    inputs = _inputs(
        options=[
            ComparisonOption(
                major="computer_science",
                credits_transferable=66,
                prospective_credits_required=124,
                prospective_credits_required_source="What-if audit, 2026-08-01",
            )
        ]
    )
    pairwise = inputs.to_pairwise_inputs(inputs.option_for("computer_science"))
    assert pairwise.prospective_credits_required == 124
    assert pairwise.prospective_credits_required_source == "What-if audit, 2026-08-01"
