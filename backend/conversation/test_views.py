"""
Tests for the authorized view.

The property worth protecting hardest: the view is what the verifier's
allowlist gets built from, so a number absent from the view must be
absent from the allowlist. That's what makes topic scoping enforceable
instead of merely requested. The last test in this file checks that end to
end against the real allowlist builder.
"""

from ai.interface import _build_number_allowlist, _numeric_variants
from conversation.router import BROAD, CAREER, CREDITS, FINANCIAL, TIMELINE
from conversation.views import build_view, view_has_any_data
from decision_paths.change_major.comparison import (
    MultiComparisonSnapshot,
    OptionOutcome,
    STATUS_CALCULATED,
    STATUS_PENDING,
)


def _line(value, label="A figure"):
    return {
        "label": label,
        "value": value,
        "source": "Test source",
        "source_date": "2026-01-01",
    }


def _dimensions(tuition=8000, semesters=2, credits_lost=6, salary=39839):
    return {
        "financial": {
            "incremental_tuition": _line(tuition),
            "incremental_total_cost": _line(tuition + 5000),
            "foregone_earnings_cost": _line(5000),
            "tuition_remaining_current": _line(15000),
            "tuition_remaining_prospective": _line(15000 + tuition),
            "incremental_semesters": _line(semesters),
        },
        "timeline": {
            "incremental_semesters": _line(semesters),
            "semesters_remaining_current": _line(3),
            "semesters_remaining_prospective": _line(3 + semesters),
            "credits_remaining_current": _line(48),
            "credits_remaining_prospective": _line(54),
        },
        "credits": {
            "credits_lost": _line(credits_lost),
            "credits_completed": _line(72),
            "credits_transferable": _line(66),
            "credits_required_current": _line(120),
            "credits_required_prospective": _line(120),
            "credits_remaining_prospective": _line(54),
        },
        # Split to mirror comparison.py's _dimensions_from_result(): salary
        # figures live under "earnings" (permitted for FINANCIAL too),
        # occupations/job-market data stays under the narrower "career".
        "earnings": {
            "median_salary_current": _line(30396),
            "median_salary_prospective": _line(70235),
            "annual_salary_delta": _line(salary),
            "earnings_context": [],
        },
        "career": {
            "career_context": [],
        },
        "program": {"official_program_name": "BS in Computer Science", "degree_type": "BS"},
    }


def _snapshot():
    return MultiComparisonSnapshot(
        anchor_key="psychology",
        anchor_display="Psychology",
        credits_completed=72,
        outcomes=[
            OptionOutcome(
                major_key="computer_science",
                major_display="Computer Science",
                status=STATUS_CALCULATED,
                dimensions=_dimensions(),
            ),
            OptionOutcome(
                major_key="information_technology",
                major_display="Information Technology",
                status=STATUS_CALCULATED,
                dimensions=_dimensions(tuition=6000, semesters=1),
            ),
            OptionOutcome(
                major_key="mechanical_engineering",
                major_display="Mechanical Engineering",
                status=STATUS_PENDING,
                missing_fields=["credits_transferable"],
            ),
        ],
        assumptions=["Full-time enrollment assumed."],
        limitations=["Median outcomes, not a prediction."],
    )


ALL_ACTIVE = [
    "psychology",
    "computer_science",
    "information_technology",
    "mechanical_engineering",
]


# --- topic scoping --------------------------------------------------------


def test_broad_view_includes_every_dimension():
    view = build_view(_snapshot(), BROAD, ALL_ACTIVE)
    data = view["options"][0]["data"]
    assert set(data) == {"financial", "timeline", "credits", "earnings", "career", "program"}


def test_career_view_excludes_financial_data():
    view = build_view(_snapshot(), CAREER, ALL_ACTIVE)
    data = view["options"][0]["data"]
    assert "career" in data
    assert "earnings" in data
    assert "financial" not in data


def test_financial_view_keeps_the_figures_that_drive_cost():
    """Extra semesters are what create extra tuition, so a financial
    answer that can't mention them can state a number it can't explain."""
    view = build_view(_snapshot(), FINANCIAL, ALL_ACTIVE)
    data = view["options"][0]["data"]
    assert "financial" in data
    assert "timeline" in data
    assert "career" not in data


def test_financial_view_gains_earnings_but_not_occupations():
    """Permitted per the architecture: early-career earnings context is
    financially relevant, but Job Market Demand/occupation data is not --
    that stays CAREER-exclusive even though it used to live in the same
    combined block."""
    data = build_view(_snapshot(), FINANCIAL, ALL_ACTIVE)["options"][0]["data"]
    assert "earnings" in data
    assert "career" not in data


def test_timeline_view_keeps_credits():
    data = build_view(_snapshot(), TIMELINE, ALL_ACTIVE)["options"][0]["data"]
    assert set(data) == {"timeline", "credits"}


def test_credits_view_scope():
    data = build_view(_snapshot(), CREDITS, ALL_ACTIVE)["options"][0]["data"]
    assert "credits" in data
    assert "career" not in data
    assert "earnings" not in data
    assert "financial" not in data


def test_assumptions_and_limitations_survive_narrow_scoping():
    """Scoping the numbers must not strip the caveats -- that would
    produce a confident answer with its honesty removed."""
    view = build_view(_snapshot(), CAREER, ALL_ACTIVE)
    assert view["assumptions"]
    assert view["limitations"]


# --- option scoping, independent of topic --------------------------------


def test_narrowing_options_does_not_change_the_topic_data():
    narrow = build_view(_snapshot(), CAREER, ["psychology", "computer_science"])
    broad_options = build_view(_snapshot(), CAREER, ALL_ACTIVE)

    assert len(narrow["options"]) == 1
    assert len(broad_options["options"]) == 3
    assert set(narrow["options"][0]["data"]) == set(broad_options["options"][0]["data"])


def test_inactive_options_are_absent_not_flagged():
    """An option the student removed must not appear at all -- leaving it
    in as 'inactive' would let its numbers be quoted back at them."""
    view = build_view(_snapshot(), BROAD, ["psychology", "computer_science"])
    names = [o["major"] for o in view["options"]]
    assert names == ["Computer Science"]


def test_topic_scoping_never_drops_an_option():
    for scope in (BROAD, FINANCIAL, CAREER, TIMELINE, CREDITS):
        view = build_view(_snapshot(), scope, ALL_ACTIVE)
        assert len(view["options"]) == 3, f"{scope} dropped an option"


# --- pending options ------------------------------------------------------


def test_pending_option_appears_with_no_numbers():
    view = build_view(_snapshot(), BROAD, ALL_ACTIVE)
    pending = [o for o in view["options"] if o["status"] == STATUS_PENDING][0]
    assert "data" not in pending
    assert pending["missing_fields"] == ["credits_transferable"]


def test_view_has_any_data_is_false_when_everything_is_pending():
    snapshot = _snapshot()
    snapshot.outcomes = [o for o in snapshot.outcomes if o.status == STATUS_PENDING]
    view = build_view(snapshot, BROAD, ALL_ACTIVE)
    assert not view_has_any_data(view)


# --- the point of all this: allowlist enforcement -------------------------


def test_career_view_allowlist_excludes_tuition_figures():
    """End to end against the real verifier helper. A tuition number in a
    career answer has nothing to match against, so it fails grounding --
    not because a rule forbade it, but because it was never authorized."""
    career_view = build_view(_snapshot(), CAREER, ALL_ACTIVE)
    allowlist = _build_number_allowlist(career_view)

    tuition_variants = _numeric_variants(8000.0)
    assert not (tuition_variants & allowlist)

    salary_variants = _numeric_variants(39839.0)
    assert salary_variants & allowlist


def test_broad_view_allowlist_includes_both():
    broad_view = build_view(_snapshot(), BROAD, ALL_ACTIVE)
    allowlist = _build_number_allowlist(broad_view)

    assert _numeric_variants(8000.0) & allowlist
    assert _numeric_variants(39839.0) & allowlist


def test_removed_option_numbers_leave_the_allowlist():
    """Narrowing to CS and Psychology must make IT's distinct figures
    unquotable."""
    it_only_figure = 6000.0
    full = _build_number_allowlist(build_view(_snapshot(), FINANCIAL, ALL_ACTIVE))
    narrowed = _build_number_allowlist(
        build_view(_snapshot(), FINANCIAL, ["psychology", "computer_science"])
    )

    assert _numeric_variants(it_only_figure) & full
    assert not (_numeric_variants(it_only_figure) & narrowed)
