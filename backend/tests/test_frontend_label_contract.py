"""
Locks the line-item labels the frontend looks up by name.

This exists because of a real bug. Stage 4 renamed several labels
("Annual starting salary difference" -> "Difference in early-career
earnings (1 year after graduation)", and so on). The frontend's node map
finds line items by matching a fragment of the label, so those lookups
silently started returning nothing — and because the detail panel gates its
whole provenance block on having a line item, the Career Outlook and Salary
Outlook nodes quietly lost their sources, assumptions, and limitations. No
error, no failing test, just missing sections nobody noticed until someone
clicked the node.

A label is therefore part of the API contract, not just display text.
Renaming one is allowed, but it has to be a deliberate change that breaks
this test and gets mirrored in frontend/lib/nodes.ts — not something that
slips through.
"""

import pytest

from data_loading.loader import build_reference_data
from decision_paths.change_major.engine import calculate
from decision_paths.change_major.formatter import format_result
from decision_paths.change_major.inputs import ChangeMajorInputs


@pytest.fixture
def formatted():
    result = calculate(
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="psychology_bs",
            credits_completed=72,
            credits_transferable=60,
        ),
        build_reference_data("unt"),
    )
    return format_result(result)


def _labels(formatted: dict) -> list[str]:
    return [
        *(li["label"] for li in formatted["line_items"]),
        *(li["label"] for li in formatted["comparison"]["staying"]["line_items"]),
        *(li["label"] for li in formatted["comparison"]["switching"]["line_items"]),
    ]


# Fragments frontend/lib/nodes.ts passes to findLineItem(). Keep in sync.
FRONTEND_LOOKUPS = [
    "Estimated total difference",
    "Additional tuition",
    "Estimated early-career income delayed",
    "Additional semesters",
    "count toward nothing",
    "Credits already completed",
    "Credits that transfer",
    "Difference in early-career earnings",
]


@pytest.mark.parametrize("fragment", FRONTEND_LOOKUPS)
def test_frontend_label_lookup_still_matches(fragment, formatted):
    labels = _labels(formatted)
    assert any(fragment.lower() in label.lower() for label in labels), (
        f"No line item matches '{fragment}'. frontend/lib/nodes.ts looks this "
        "up by name; if the label was renamed on purpose, update nodes.ts and "
        "this list together."
    )


def test_per_major_earnings_labels_are_addressable(formatted):
    """The career nodes build these lookups from the major display names in
    the summary, so the two have to line up exactly."""
    labels = _labels(formatted)
    for major_key in ("current_major", "prospective_major"):
        major = formatted["summary"][major_key]
        expected = f"Median earnings 1 year after graduation — {major}"
        assert expected in labels, (
            f"Expected a line item labelled '{expected}'. The Career Outlook "
            "and Salary Outlook nodes construct this string from "
            f"summary.{major_key}."
        )


def test_earnings_context_carries_what_the_panel_renders(formatted):
    """The always-visible 'Data limitation' section and the 4/5-year rows
    are built from earnings_context, so its shape is load-bearing."""
    contexts = formatted["earnings_context"]
    assert len(contexts) == 2

    summary_majors = {
        formatted["summary"]["current_major"],
        formatted["summary"]["prospective_major"],
    }
    # The panel matches a context to a node by major name.
    assert {c["major"] for c in contexts} == summary_majors

    for ctx in contexts:
        assert ctx["population_note"], "every major needs the population caveat"
        assert ctx["source"], "source must be visible in the panel"
        assert ctx["source_date"], "dataset date must be visible in the panel"

        periods = [t["period"] for t in ctx["trajectory"]]
        assert periods == ["1yr", "4yr", "5yr"]

        for point in ctx["trajectory"]:
            assert point["label"], "each row needs a student-facing label"
            # Raw dataset field names must not reach the UI.
            assert "EARN_MDN" not in point["label"]
            assert point["status"] in (
                "available",
                "privacy_suppressed",
                "unavailable",
            )
            if point["status"] != "available":
                # Never a zero, and always a reason the panel can show.
                assert point["value"] is None
                assert point["status_note"]


def test_shared_category_note_is_present_where_it_applies(formatted):
    """Psychology B.S. shares a federal category with the B.A., so its
    context must say so — that's the text the panel renders verbatim."""
    psych = next(
        c for c in formatted["earnings_context"] if "Psychology" in c["major"]
    )
    assert psych["covers"], "shared-category majors must explain what's covered"
    assert "B.A." in psych["covers"] and "B.S." in psych["covers"]


def test_no_student_facing_label_says_starting_salary(formatted):
    """The figure is median earnings at a stated time point, not a starting
    salary, and the UI must never call it one."""
    for label in _labels(formatted):
        assert "starting salary" not in label.lower()

    for ctx in formatted["earnings_context"]:
        for point in ctx["trajectory"]:
            assert "starting salary" not in point["label"].lower()
