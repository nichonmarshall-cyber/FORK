"""
Shared fixtures for the API tests.

The audit PDF is generated rather than committed. Real degree audits are
education records and are gitignored; this builds a PDF carrying the redacted
fixture text so the upload path — including pypdf's text extraction — is
exercised end to end without a student's record in the repository.

A sanitized PDF-level fixture can replace this later without any test changing
shape.
"""

import io
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "audit_import/unt/tests/fixtures"


@pytest.fixture
def audit_pdf() -> bytes:
    pytest.importorskip("reportlab", reason="reportlab not installed")

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    text = (FIXTURES / "unt_audit_standard.txt").read_text(encoding="utf-8")
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