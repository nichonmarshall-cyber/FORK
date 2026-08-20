"""
Confirmed audit -> Change Major engine.

The point of contention these protect: a degree audit establishes completed
and in-progress hours, and it does not establish how many of those hours count
toward a different degree. The adapter has to supply the first two and refuse
the third, and refuse it visibly rather than by omission.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from adapters.confirmed_record_to_inputs import build_inputs_from_confirmed_record
from audit_import.unt.parser import parse_audit_text
from session.context import SessionAcademicContext
from session.store import academic_sessions

FIXTURES = Path(__file__).resolve().parent.parent / "audit_import/unt/tests/fixtures"


@pytest.fixture
def client():
    academic_sessions.clear()
    return TestClient(main.app)


@pytest.fixture
def confirmed_session():
    record = parse_audit_text((FIXTURES / "unt_audit_standard.txt").read_text(encoding="utf-8"))
    session = SessionAcademicContext(session_id="test")
    session.attach_record(record)
    session.confirm()
    return session


# --- The adapter -------------------------------------------------------


def test_supplies_the_two_figures_the_audit_establishes(confirmed_session):
    inputs = build_inputs_from_confirmed_record(confirmed_session)
    assert inputs is not None
    assert inputs.credits_completed == 81
    assert inputs.credits_in_progress == 18
    assert inputs.credits_source == "UNT Degree Audit, confirmed by you"
    assert inputs.credits_source_date == "08/18/2026 03:18 PM"
    assert inputs.totals_confirmed is True


def test_never_supplies_transferable_credits(confirmed_session):
    """The one number a degree audit cannot give.

    Passing credits_completed would assume everything transfers; passing a
    fraction would invent a rule; passing 0 would assert nothing transfers.
    All three are worse than saying so.
    """
    inputs = build_inputs_from_confirmed_record(confirmed_session)
    assert inputs is not None
    assert not hasattr(inputs, "credits_transferable")
    assert "credits_transferable" not in inputs.model_dump()


def test_explains_why_transferable_is_missing(confirmed_session):
    """Absence alone reads as an oversight. The reason travels with it, in
    both a form tests can assert on and a form a student can read."""
    inputs = build_inputs_from_confirmed_record(confirmed_session)
    assert inputs is not None

    entry = next(u for u in inputs.unavailable if u.field == "credits_transferable")
    assert entry.reason_code == "requires_course_level_matching"
    assert "course-by-course" in entry.user_message
    assert "What-If" in entry.user_message
    # Student-facing copy stays free of internal vocabulary.
    for term in ("matcher", "catalog specification", "adapter", "None"):
        assert term not in entry.user_message


def test_names_the_prospective_major_when_known(confirmed_session):
    inputs = build_inputs_from_confirmed_record(
        confirmed_session, prospective_label="Information Technology"
    )
    assert inputs is not None
    entry = next(u for u in inputs.unavailable if u.field == "credits_transferable")
    assert "Information Technology" in entry.user_message


def test_unconfirmed_session_supplies_nothing():
    """Parsing is not confirming. A record the student hasn't checked yields
    no engine inputs at all, so no caller can route around the review step."""
    record = parse_audit_text((FIXTURES / "unt_audit_standard.txt").read_text(encoding="utf-8"))
    session = SessionAcademicContext(session_id="unconfirmed")
    session.attach_record(record)

    assert build_inputs_from_confirmed_record(session) is None


def test_reverting_to_manual_withdraws_the_inputs(confirmed_session):
    confirmed_session.switch_to_manual()
    assert build_inputs_from_confirmed_record(confirmed_session) is None


# --- Through the API ---------------------------------------------------


def test_inputs_appear_only_after_confirmation(client, audit_pdf):
    uploaded = client.post(
        "/audit/unt/upload",
        files={"file": ("audit.pdf", audit_pdf, "application/pdf")},
    ).json()
    assert "change_major_inputs" not in uploaded

    confirmed = client.post(f"/audit/session/{uploaded['session_id']}/confirm").json()
    assert confirmed["change_major_inputs"]["credits_completed"] == 81
    assert confirmed["change_major_inputs"]["credits_in_progress"] == 18


def test_confirmed_figures_run_through_the_engine(client, audit_pdf):
    """The whole point of Option B: document-derived hours reach the same
    deterministic engine the manual form uses, and the provenance follows
    them into the result."""
    session_id = client.post(
        "/audit/unt/upload",
        files={"file": ("audit.pdf", audit_pdf, "application/pdf")},
    ).json()["session_id"]
    inputs = client.post(f"/audit/session/{session_id}/confirm").json()["change_major_inputs"]

    result = client.post(
        "/decision-paths/change-major/calculate",
        json={
            "current_major": "computer_science",
            "prospective_major": "information_technology",
            "credits_completed": inputs["credits_completed"],
            # Still the student's own number -- the audit doesn't supply it.
            "credits_transferable": 70,
            "credits_source": inputs["credits_source"],
            "credits_source_date": inputs["credits_source_date"],
            "credits_in_progress": inputs["credits_in_progress"],
        },
    )
    assert result.status_code == 200
    body = result.json()

    sources = [li["source"] for li in body["line_items"]]
    assert any("confirmed by you" in s for s in sources)
    # And the estimate is still labelled as one, beside it.
    assert any("Student-reported" in s for s in sources)


def test_engine_still_rejects_transferable_above_completed(client, audit_pdf):
    """A confirmed audit doesn't loosen any existing validation."""
    session_id = client.post(
        "/audit/unt/upload",
        files={"file": ("audit.pdf", audit_pdf, "application/pdf")},
    ).json()["session_id"]
    client.post(f"/audit/session/{session_id}/confirm")

    response = client.post(
        "/decision-paths/change-major/calculate",
        json={
            "current_major": "computer_science",
            "prospective_major": "information_technology",
            "credits_completed": 81,
            "credits_transferable": 99,
            "credits_source": "UNT Degree Audit, confirmed by you",
        },
    )
    assert response.status_code in (400, 422)


def test_nothing_claims_verification(client, audit_pdf):
    session_id = client.post(
        "/audit/unt/upload",
        files={"file": ("audit.pdf", audit_pdf, "application/pdf")},
    ).json()["session_id"]
    body = client.post(f"/audit/session/{session_id}/confirm").text.lower()
    assert "verif" not in body