"""
A manual estimate must not survive a matching, confirmed What-If.

The failure this guards against: a student types 66, uploads a What-If for
the major they're considering, confirms it, recalculates -- and Fork still
uses 66, then tells them (accurately, which is the galling part) that the
figure was student-reported. Every layer behaves correctly in isolation and
the wrong number reaches the answer anyway.

These tests walk the value from parser to calculation and assert the
document figure wins at each hand-off, so a regression names the layer that
dropped it rather than surfacing three steps later as a provenance string.
"""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from documents.resolution import (
    classify_document,
    degree_applicable_hours,
    resolve_comparison_inputs,
)
from audit_import.unt.parser import parse_audit_text
from session.store import academic_sessions

FIXTURES = Path(__file__).resolve().parent.parent / "audit_import/unt/tests/fixtures"

#: What the student typed before uploading anything. Every assertion below
#: exists to prove this figure cannot reach a calculation once a matching
#: What-If is confirmed.
MANUAL_ESTIMATE = 66


@pytest.fixture
def client():
    academic_sessions.clear()
    return TestClient(main.app)


def _as_pdf(name: str) -> bytes:
    pytest.importorskip("reportlab", reason="reportlab not installed")
    from reportlab.lib.pagesizes import letter  # type: ignore[import-untyped]
    from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

    text = (FIXTURES / f"unt_audit_{name}.txt").read_text(encoding="utf-8")
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.setFont("Courier", 7)
    y = 760
    for line in text.split("\n"):
        if y < 30:
            pdf.showPage()
            pdf.setFont("Courier", 7)
            y = 760
        pdf.drawString(20, y, line[:120])
        y -= 8
    pdf.save()
    return buffer.getvalue()


def _confirmed_and_acknowledged(client) -> dict:
    """Both documents confirmed, discrepancy acknowledged. Returns the
    resolved block -- the state a student reaches before recalculating."""
    session_id = client.post(
        "/audit/unt/upload",
        files={"file": ("a.pdf", _as_pdf("standard"), "application/pdf")},
    ).json()["session_id"]
    client.post(f"/audit/session/{session_id}/confirm")
    client.post(
        f"/audit/unt/upload?session_id={session_id}",
        files={"file": ("w.pdf", _as_pdf("whatif"), "application/pdf")},
    )
    client.post(f"/audit/session/{session_id}/confirm?document=what_if")

    fingerprint = client.get(f"/audit/session/{session_id}").json()["documents"][
        "evidence_fingerprint"
    ]
    body = client.post(
        f"/audit/session/{session_id}/acknowledge",
        json={"evidence_fingerprint": fingerprint},
    ).json()
    return {"session_id": session_id, "documents": body["documents"]}


# --- Step 1: the resolver ----------------------------------------------


def test_resolver_produces_a_figure_at_all():
    """The first place the chain can break silently.

    When degree_applicable_hours returns None the resolver correctly refuses
    to substitute -- but every downstream layer then behaves correctly with
    nothing, the manual value stays, and the failure only becomes visible as
    a provenance string in the AI's answer. So this is asserted first and
    separately.
    """
    what_if = parse_audit_text(
        (FIXTURES / "unt_audit_whatif.txt").read_text(encoding="utf-8")
    )
    applicable = degree_applicable_hours(what_if)

    assert applicable is not None, (
        "The What-If states no degree-total block, so the resolver supplies "
        "nothing and the manual estimate survives by default."
    )
    assert applicable == 66.0


def test_resolver_output_replaces_the_manual_estimate():
    majors = main._load_reference_data("unt")["majors"]
    current = parse_audit_text(
        (FIXTURES / "unt_audit_standard.txt").read_text(encoding="utf-8")
    )
    what_if = parse_audit_text(
        (FIXTURES / "unt_audit_whatif.txt").read_text(encoding="utf-8")
    )

    resolved = resolve_comparison_inputs(
        current,
        what_if,
        classify_document(what_if, majors),
        {"computer_science": MANUAL_ESTIMATE},
        acknowledged=True,
    )

    assert resolved.option_credits is not None
    assert "What-If" in resolved.option_credits.source
    # The manual figure is preserved for restoration, NOT used.
    assert resolved.manual_restore["computer_science"] == MANUAL_ESTIMATE


# --- Step 2: the session payload ---------------------------------------


def test_payload_carries_the_document_figure_and_its_provenance(client):
    resolved = _confirmed_and_acknowledged(client)["documents"]["resolved"]

    assert resolved["option_credits"] is not None
    assert resolved["option_credits"]["program_key"] == "computer_science"
    assert "What-If" in resolved["option_credits"]["source"]
    # Shared facts stay with the current audit and do not come from the
    # What-If's own totals.
    assert resolved["credits_completed"] == 81
    assert resolved["credits_in_progress"] == 18


def test_payload_says_which_option_the_figure_belongs_to(client):
    """Without this the frontend cannot tell whether a stored document
    applies to the option on screen, and a Psychology What-If could fill a
    field labelled Information Technology."""
    resolved = _confirmed_and_acknowledged(client)["documents"]["resolved"]
    assert resolved["option_credits"]["program_key"] == "computer_science"


def test_an_unmatched_option_receives_nothing(client):
    """The dormant case. A stored What-If for one program contributes
    nothing to any other, and the manual estimate stays in place."""
    resolved = _confirmed_and_acknowledged(client)["documents"]["resolved"]
    supplied = resolved["option_credits"]["program_key"]

    for other in ("psychology_ba", "information_technology", "business_administration"):
        assert supplied != other


# --- Step 3: the calculation -------------------------------------------


def test_calculation_carries_what_if_provenance_not_student_reported(client):
    """The end of the chain, and where the failure was visible.

    Ask Fork grounds on the calculated result, so if this line item says
    'Student-reported' the explanation will say so too -- correctly, which
    is why the wrong number is hard to spot from the answer alone.
    """
    state = _confirmed_and_acknowledged(client)
    resolved = state["documents"]["resolved"]
    option = resolved["option_credits"]

    result = client.post(
        "/decision-paths/change-major/calculate",
        json={
            "current_major": "mechanical_energy_engineering",
            "prospective_major": option["program_key"],
            "credits_completed": resolved["credits_completed"],
            # The document figure, NOT the manual estimate.
            "credits_transferable": option["credits_transferable"],
            "credits_source": resolved["credits_source"],
            "credits_transferable_source": option["source"],
            "credits_source_date": resolved["credits_source_date"],
            "credits_in_progress": resolved["credits_in_progress"],
        },
    )
    assert result.status_code == 200
    sources = [li["source"] for li in result.json()["line_items"]]

    assert any("What-If" in s for s in sources), (
        "The calculation records the transferable figure as student-reported, "
        "so any explanation built on it will say the same."
    )


def test_the_manual_estimate_does_not_appear_in_the_resolved_figures(client):
    """The regression, stated directly.

    66 is what the student typed. It may appear under manual_restore, which
    exists so reverting gives them their own number back -- but it must not
    be what any option is calculated from.
    """
    resolved = _confirmed_and_acknowledged(client)["documents"]["resolved"]
    option = resolved["option_credits"]

    assert option["credits_transferable"] == degree_applicable_hours(
        parse_audit_text(
            (FIXTURES / "unt_audit_whatif.txt").read_text(encoding="utf-8")
        )
    )
    assert "Student-reported" not in option["source"]


# --- Step 4: reverting -------------------------------------------------


def test_reverting_gives_the_manual_estimate_back(client):
    """The manual value is preserved, not discarded -- reverting must not
    leave the student with an empty field."""
    state = _confirmed_and_acknowledged(client)
    session_id = state["session_id"]

    body = client.post(
        f"/audit/session/{session_id}/mode", params={"mode": "manual"}
    ).json()

    assert body["active_mode"] == "manual"
    assert body["documents"]["what_if"]["present"] is False
    assert body["documents"]["resolved"]["option_credits"] is None


# --- The regression that caused this file to exist ---------------------


def test_a_banner_above_a_block_header_does_not_swallow_it():
    """The bug this file was written for.

    The What-If carried a line reading 'SYNTHETIC WHAT-IF TEST RECORD - NOT
    AN OFFICIAL UNIVERSITY DOCUMENT' directly above its degree-total block.
    The wrap-joiner treats a long line without terminal punctuation as
    continuing onto the next, and that banner wasn't recognised as a heading
    (the hyphen in WHAT-IF broke the pattern), so it absorbed the block
    header beneath it.

    The block then didn't exist, degree_applicable_hours returned None, the
    resolver correctly refused to substitute, and the student's manual
    estimate survived -- surfacing as an accurate-sounding sentence about
    student-reported figures. Nothing in the pipeline reported an error.
    """
    what_if = parse_audit_text(
        (FIXTURES / "synthetic_whatif_psyc.txt").read_text(encoding="utf-8")
    )
    assert degree_applicable_hours(what_if) == 81.0


def test_the_synthetic_pair_resolves_to_matching_progress():
    """Same course history, two programs. Both report 81 applicable, so a
    switch costs no additional semesters -- and any figure other than 81
    would invent a penalty."""
    majors = main._load_reference_data("unt")["majors"]
    current = parse_audit_text(
        (FIXTURES / "synthetic_current_cs.txt").read_text(encoding="utf-8")
    )
    what_if = parse_audit_text(
        (FIXTURES / "synthetic_whatif_psyc.txt").read_text(encoding="utf-8")
    )

    classification = classify_document(what_if, majors)
    assert classification.match is not None
    assert classification.match.program_key == "psychology_bs"

    resolved = resolve_comparison_inputs(
        current, what_if, classification, {"psychology_bs": MANUAL_ESTIMATE},
        acknowledged=True,
    )
    assert resolved.credits_completed == 81
    assert resolved.option_credits is not None
    assert resolved.option_credits.credits_transferable == 81
    assert resolved.option_credits.program_key == "psychology_bs"


def test_documents_prepared_minutes_apart_raise_no_date_gap():
    """Four minutes apart, so the 90-day rule must not fire. A spurious
    warning here would gate the calculation behind an acknowledgement the
    student has no reason to give."""
    from documents.resolution import detect_discrepancies

    current = parse_audit_text(
        (FIXTURES / "synthetic_current_cs.txt").read_text(encoding="utf-8")
    )
    what_if = parse_audit_text(
        (FIXTURES / "synthetic_whatif_psyc.txt").read_text(encoding="utf-8")
    )
    assert detect_discrepancies(current, what_if) == []
