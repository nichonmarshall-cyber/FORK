"""
API tests for the degree-audit session endpoints.

Also asserts the thing this batch most needed not to break: the existing
manual Change Major path still works exactly as it did, untouched by any of
the new machinery.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from session.store import academic_sessions

FIXTURES = Path(__file__).resolve().parent.parent / "audit_import/unt/tests/fixtures"


@pytest.fixture
def client():
    academic_sessions.clear()
    return TestClient(main.app)


@pytest.fixture
def audit_pdf():
    """Build a PDF carrying the redacted fixture text.

    The real audits stay out of the repository, so the integration path is
    exercised against a generated PDF containing the same text. A sanitized
    PDF-level fixture can replace this without the tests changing shape.
    """
    pytest.importorskip("reportlab", reason="reportlab not installed")
    import io

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    text = (FIXTURES / "unt_audit_standard.txt").read_text()
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


# --- Manual mode is untouched ------------------------------------------


def test_manual_change_major_still_works(client):
    """The existing path, unchanged. Nothing in this batch may alter it."""
    response = client.post(
        "/decision-paths/change-major/calculate",
        json={
            "current_major": "computer_science",
            "prospective_major": "information_technology",
            "credits_completed": 72,
            "credits_transferable": 66,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["credits_lost"] == 6
    assert body["comparison"]["staying"]["line_items"]


def test_manual_provenance_still_defaults_to_student_reported(client):
    response = client.post(
        "/decision-paths/change-major/calculate",
        json={
            "current_major": "computer_science",
            "prospective_major": "psychology",
            "credits_completed": 60,
            "credits_transferable": 45,
        },
    )
    sources = [li["source"] for li in response.json()["line_items"]]
    assert any("Student-reported" in s for s in sources)


def test_legacy_generic_audit_endpoint_still_present(client):
    """The school-agnostic parser stays as the path for documents the UNT
    parser doesn't recognise."""
    response = client.post(
        "/audit/parse",
        files={"file": ("x.txt", b"not a pdf", "text/plain")},
    )
    assert response.status_code == 415


# --- Upload and review -------------------------------------------------


def test_upload_returns_a_review_awaiting_confirmation(client, audit_pdf):
    response = client.post(
        "/audit/unt/upload",
        files={"file": ("audit.pdf", audit_pdf, "application/pdf")},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["active_mode"] == "manual"
    assert body["uploaded_source"]["present"] is True
    assert body["uploaded_source"]["awaiting_review"] is True
    assert body["uploaded_source"]["is_active"] is False
    assert body["review"]["completed_hours"] == 81.0
    assert body["review"]["in_progress_hours"] == 18.0


def test_rejects_a_non_pdf(client):
    response = client.post(
        "/audit/unt/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415


def test_rejects_an_empty_file(client):
    response = client.post(
        "/audit/unt/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400


def test_unreadable_pdf_is_a_technical_failure_without_a_traceback(client):
    """A corrupt file is a real error. The response says what happened without
    leaking an exception type or a stack trace."""
    response = client.post(
        "/audit/unt/upload",
        files={"file": ("broken.pdf", b"%PDF-1.4 garbage", "application/pdf")},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Traceback" not in detail
    assert "Error" not in detail


# --- Correct and confirm -----------------------------------------------


def test_full_review_correct_confirm_flow(client, audit_pdf):
    uploaded = client.post(
        "/audit/unt/upload",
        files={"file": ("audit.pdf", audit_pdf, "application/pdf")},
    ).json()
    session_id = uploaded["session_id"]

    corrected = client.post(
        f"/audit/session/{session_id}/correct",
        json={"field": "catalog_year", "value": "Fall 2025"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["review"]["catalog_year"] == "Fall 2025"
    assert corrected.json()["uploaded_source"]["awaiting_review"] is True

    confirmed = client.post(f"/audit/session/{session_id}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["active_mode"] == "confirmed_upload"
    assert confirmed.json()["uploaded_source"]["is_active"] is True
    assert confirmed.json()["active_source_label"] == "the academic information you confirmed"


def test_switching_back_to_manual_clears_the_record(client, audit_pdf):
    session_id = client.post(
        "/audit/unt/upload",
        files={"file": ("audit.pdf", audit_pdf, "application/pdf")},
    ).json()["session_id"]

    client.post(f"/audit/session/{session_id}/confirm")
    switched = client.post(f"/audit/session/{session_id}/mode", params={"mode": "manual"})

    assert switched.status_code == 200
    body = switched.json()
    assert body["active_mode"] == "manual"
    assert body["uploaded_source"]["present"] is False
    assert "review" not in body


def test_cannot_activate_an_unconfirmed_record(client, audit_pdf):
    session_id = client.post(
        "/audit/unt/upload",
        files={"file": ("audit.pdf", audit_pdf, "application/pdf")},
    ).json()["session_id"]

    response = client.post(
        f"/audit/session/{session_id}/mode", params={"mode": "confirmed_upload"}
    )
    assert response.status_code == 400
    assert "confirm" in response.json()["detail"].lower()


def test_expired_session_explains_itself(client):
    response = client.get("/audit/session/does-not-exist")
    assert response.status_code == 404
    assert "expired" in response.json()["detail"].lower()


def test_no_endpoint_claims_verification(client, audit_pdf):
    """Fork checked its own reading with the student. Nothing may describe that
    as verification with UNT."""
    session_id = client.post(
        "/audit/unt/upload",
        files={"file": ("audit.pdf", audit_pdf, "application/pdf")},
    ).json()["session_id"]

    client.post(f"/audit/session/{session_id}/confirm")
    body = client.get(f"/audit/session/{session_id}").text.lower()

    assert "verified" not in body
    assert "verif" not in body


def test_no_calculation_is_exposed_yet(client, audit_pdf):
    """The matcher isn't built. Nothing here may emit transferable credits or a
    remaining-hours figure, because nothing yet stands behind one."""
    session_id = client.post(
        "/audit/unt/upload",
        files={"file": ("audit.pdf", audit_pdf, "application/pdf")},
    ).json()["session_id"]
    client.post(f"/audit/session/{session_id}/confirm")

    body = client.get(f"/audit/session/{session_id}").json()
    assert "credits_transferable" not in str(body)
    assert "prospective_credits_required" not in str(body)
    assert body.get("degree_match_results") is None