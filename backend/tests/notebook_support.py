"""Shared setup for the account and notebook tests."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parent.parent / "audit_import/unt/tests/fixtures"
CSRF = {"X-Fork-CSRF": "1"}
PASSWORD = "correct horse battery"


def fixture_pdf(filename: str) -> bytes:
    pytest.importorskip("reportlab", reason="reportlab not installed")
    from reportlab.lib.pagesizes import letter  # type: ignore[import-untyped]
    from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

    text = (FIXTURES / filename).read_text(encoding="utf-8")
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


def new_client() -> TestClient:
    import main

    return TestClient(main.app)


def register(client: TestClient, email: str, password: str = PASSWORD, **extra):
    return client.post(
        "/account/register",
        json={"email": email, "password": password, **extra},
        headers=CSRF,
    )


def signed_in(email: str) -> TestClient:
    client = new_client()
    response = register(client, email)
    assert response.status_code == 201, response.text
    return client


def upload_confirmed(client: TestClient, filename: str, session_id: str | None = None) -> str:
    url = "/audit/unt/upload" + (f"?session_id={session_id}" if session_id else "")
    body = client.post(url, files={"file": ("a.pdf", fixture_pdf(filename), "application/pdf")})
    assert body.status_code == 200, body.text
    payload = body.json()
    sid = payload["session_id"]
    which = "what_if" if session_id else "current"
    confirmed = client.post(f"/audit/session/{sid}/confirm?document={which}")
    assert confirmed.status_code == 200, confirmed.text
    return sid


def save_audit(client: TestClient, session_id: str, which: str = "current"):
    return client.post(
        "/notebook/documents/from-audit",
        json={"audit_session_id": session_id, "document": which},
        headers=CSRF,
    )


def events(client: TestClient) -> list[dict]:
    return client.get("/notebook/timeline").json()["events"]
