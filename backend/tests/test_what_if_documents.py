"""
What-If audits as a source of option-specific applicable credits.

The distinction these exist to protect: a current audit establishes what a
student has EARNED, and a What-If establishes what applies to ONE degree.
Conflating them produces a number that looks document-derived and quietly
assumes everything transfers.

Cross-program cases use synthetic records, labelled where they appear. No real
What-If for a different major exists — both fixtures are Computer Science for
the same student — so the exact-match rules are exercised against constructed
records rather than PDFs. That is a coverage limitation, not a design one.
"""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from audit_import.unt.parser import parse_audit_text
from documents.resolution import (
    DocumentRole,
    MatchQuality,
    classify_document,
    degree_applicable_hours,
    detect_discrepancies,
    resolve_comparison_inputs,
)
from session.store import academic_sessions

FIXTURES = Path(__file__).resolve().parent.parent / "audit_import/unt/tests/fixtures"


@pytest.fixture
def client():
    academic_sessions.clear()
    return TestClient(main.app)


@pytest.fixture(scope="module")
def majors():
    return main._load_reference_data("unt")["majors"]


def _record(name: str):
    return parse_audit_text((FIXTURES / f"unt_audit_{name}.txt").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def current_record():
    return _record("standard")


@pytest.fixture(scope="module")
def what_if_record():
    return _record("whatif")


def _as_pdf(name: str) -> bytes:
    pytest.importorskip("reportlab", reason="reportlab not installed")
    # Test-only dependency, imported lazily so the module still collects
    # where it isn't installed. Type checkers flag the missing stubs; the
    # importorskip above is what actually governs this at runtime.
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


def _confirmed_pair(client) -> str:
    """Upload and confirm both documents; return the session id."""
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
    return session_id


def _acknowledge(client, session_id: str):
    fingerprint = client.get(f"/audit/session/{session_id}").json()["documents"][
        "evidence_fingerprint"
    ]
    return client.post(
        f"/audit/session/{session_id}/acknowledge",
        json={"evidence_fingerprint": fingerprint},
    )


# --- The two measures are not the same ---------------------------------


def test_applicable_hours_come_from_the_degree_block_not_the_course_list(what_if_record):
    """Summing the course list gives hours EARNED; the TOTAL HOURS block
    gives hours that APPLY to this degree.

    They coincide on this fixture, so a test asserting only the number would
    pass either way. This asserts the source.
    """
    assert degree_applicable_hours(what_if_record) == 66.0

    block = next(
        r for r in what_if_record.requirements if "TOTAL HOURS" in r.title.upper()
    )
    assert degree_applicable_hours(what_if_record) == block.hours_earned


def test_missing_degree_block_refuses_rather_than_substituting():
    """No falling back to the completed total. That substitution assumes
    everything transfers and would present the assumption as
    document-derived."""
    record = _record("whatif")
    record.requirements = [
        r for r in record.requirements if "TOTAL HOURS" not in r.title.upper()
    ]
    assert degree_applicable_hours(record) is None


def test_completed_versus_applicable_is_not_a_discrepancy(current_record, what_if_record):
    """81 earned against 66 applicable is ordinary non-transferable credit,
    not a contradiction. Reporting it as one would teach students to
    distrust correct output."""
    codes = [d.code.value for d in detect_discrepancies(current_record, what_if_record)]
    assert "shared_fact_contradiction" not in codes


# --- Discrepancy rules --------------------------------------------------


def test_date_gap_fires_on_the_real_pair(current_record, what_if_record):
    found = detect_discrepancies(current_record, what_if_record)
    gap = next(d for d in found if d.code.value == "document_date_gap")
    assert gap.magnitude == "140 days"
    assert "months apart" in gap.user_message
    assert len(found) == 1


def test_shared_fact_contradiction_defers_to_the_date_gap(current_record):
    """Documents five months apart are SUPPOSED to disagree about completed
    hours. Saying so twice turns one explicable difference into two alarms."""
    stale = _record("whatif")
    stale.audit_prepared_at = current_record.audit_prepared_at  # same day

    found = detect_discrepancies(current_record, stale)
    codes = [d.code.value for d in found]
    assert "document_date_gap" not in codes
    # Now the difference has no innocent explanation, so it is reported.
    assert "shared_fact_contradiction" in codes


def test_unreadable_date_reports_no_gap_rather_than_agreement(current_record):
    unknown = _record("whatif")
    unknown.audit_prepared_at = "sometime last spring"
    codes = [d.code.value for d in detect_discrepancies(current_record, unknown)]
    assert "document_date_gap" not in codes


# --- Exact match --------------------------------------------------------


def test_what_if_is_classified_separately_from_a_current_audit(
    current_record, what_if_record, majors
):
    assert classify_document(current_record, majors).role == DocumentRole.CURRENT_AUDIT
    assert classify_document(what_if_record, majors).role == DocumentRole.WHAT_IF_AUDIT


def test_program_resolves_to_exactly_one_major(what_if_record, majors):
    match = classify_document(what_if_record, majors).match
    assert match is not None
    assert match.quality == MatchQuality.EXACT
    assert match.program_key == "computer_science"


def test_a_cs_what_if_supplies_nothing_to_another_program(what_if_record, majors):
    """SYNTHETIC framing: the record is the real CS What-If, checked against
    the resolution rule rather than a Psychology document, which does not
    exist as a fixture."""
    classification = classify_document(what_if_record, majors)
    resolved = resolve_comparison_inputs(
        None, what_if_record, classification, {}, acknowledged=True
    )
    assert resolved.option_credits is not None
    assert resolved.option_credits.program_key == "computer_science"
    assert resolved.option_credits.program_key != "psychology_ba"


def test_ambiguous_program_supplies_nothing(what_if_record, majors):
    """SYNTHETIC: a bare 'Psychology' title matches both the B.A. and the
    B.S., and picking one would attach a B.A.'s applicable hours to a B.S.
    comparison and label it document-derived."""
    ambiguous = _record("whatif")
    ambiguous.program = "Psychology"

    match = classify_document(ambiguous, majors).match
    assert match is not None
    assert match.quality == MatchQuality.AMBIGUOUS
    assert set(match.candidates) == {"psychology_ba", "psychology_bs"}

    resolved = resolve_comparison_inputs(
        None, ambiguous, classify_document(ambiguous, majors), {}, acknowledged=True
    )
    assert resolved.option_credits is None
    assert resolved.unresolved


def test_degree_type_separates_a_ba_from_a_bs(what_if_record, majors):
    """SYNTHETIC: the document's own title carries the degree, which is what
    makes an otherwise-ambiguous subject resolvable."""
    record = _record("whatif")
    record.program = "Bachelor of Arts in Psychology"
    match = classify_document(record, majors).match
    assert match is not None
    assert match.quality == MatchQuality.EXACT
    assert match.program_key == "psychology_ba"


def test_unknown_program_supplies_nothing(majors):
    record = _record("whatif")
    record.program = "Bachelor of Science in Underwater Basket Weaving"
    match = classify_document(record, majors).match
    assert match is not None
    assert match.quality == MatchQuality.AMBIGUOUS
    assert match.candidates == []


# --- Ownership ----------------------------------------------------------


def test_current_audit_owns_shared_facts_and_what_if_owns_its_option(
    current_record, what_if_record, majors
):
    resolved = resolve_comparison_inputs(
        current_record,
        what_if_record,
        classify_document(what_if_record, majors),
        {},
        acknowledged=True,
    )
    # Shared facts come from the current audit, NOT the what-if's own totals.
    assert resolved.credits_completed == 81
    assert resolved.credits_in_progress == 18
    # The option figure comes from the what-if, and differs.
    assert resolved.option_credits is not None
    assert resolved.option_credits.credits_transferable == 66
    assert "What-If" in resolved.option_credits.source


def test_unconfirmed_what_if_supplies_nothing(client):
    session_id = client.post(
        "/audit/unt/upload",
        files={"file": ("a.pdf", _as_pdf("standard"), "application/pdf")},
    ).json()["session_id"]
    client.post(f"/audit/session/{session_id}/confirm")
    body = client.post(
        f"/audit/unt/upload?session_id={session_id}",
        files={"file": ("w.pdf", _as_pdf("whatif"), "application/pdf")},
    ).json()

    assert body["documents"]["what_if"]["present"] is True
    assert body["documents"]["what_if"]["confirmed"] is False
    assert body["documents"]["resolved"]["option_credits"] is None


# --- Acknowledgement ----------------------------------------------------


def test_discrepancy_withholds_the_option_figure_until_acknowledged(client):
    session_id = _confirmed_pair(client)
    resolved = client.get(f"/audit/session/{session_id}").json()["documents"]["resolved"]

    assert resolved["requires_acknowledgement"] is True
    assert resolved["option_credits"] is None
    # Shared facts are still available -- the student can see what their own
    # audit says while deciding about the conflict.
    assert resolved["credits_completed"] == 81


def test_acknowledgement_releases_the_option_figure(client):
    session_id = _confirmed_pair(client)
    body = _acknowledge(client, session_id).json()

    option = body["documents"]["resolved"]["option_credits"]
    assert option["program_key"] == "computer_science"
    assert option["credits_transferable"] == 66


def test_a_stale_fingerprint_is_refused(client):
    session_id = _confirmed_pair(client)
    response = client.post(
        f"/audit/session/{session_id}/acknowledge",
        json={"evidence_fingerprint": "whatever-was-on-screen-before"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "evidence_changed"


def test_correcting_a_document_invalidates_the_acknowledgement(client):
    """Permission was given for documents the student was shown. An edited
    document is not one of them."""
    session_id = _confirmed_pair(client)
    _acknowledge(client, session_id)
    assert (
        client.get(f"/audit/session/{session_id}").json()["documents"]["resolved"][
            "option_credits"
        ]
        is not None
    )

    client.post(
        f"/audit/session/{session_id}/corrections",
        json={"corrections": [{"field": "hours", "value": 4.0, "course_key": "26.1:CSCE2110"}]},
    )
    # The correction unconfirms the current audit, so there is no longer a
    # disagreement between two confirmed documents to acknowledge.
    mid = client.get(f"/audit/session/{session_id}").json()["documents"]
    assert mid["current_audit"]["confirmed"] is False
    assert mid["resolved"]["credits_completed"] is None

    # Reconfirming brings the disagreement back, and permission has to be
    # given again rather than carried over.
    after = client.post(f"/audit/session/{session_id}/confirm").json()["documents"]
    assert after["resolved"]["requires_acknowledgement"] is True
    assert after["resolved"]["option_credits"] is None


def test_replacing_the_what_if_invalidates_the_acknowledgement(client):
    session_id = _confirmed_pair(client)
    _acknowledge(client, session_id)

    client.post(
        f"/audit/unt/upload?session_id={session_id}",
        files={"file": ("w2.pdf", _as_pdf("whatif"), "application/pdf")},
    )
    resolved = client.get(f"/audit/session/{session_id}").json()["documents"]["resolved"]
    assert resolved["option_credits"] is None


# --- Revert vs. dormancy ------------------------------------------------


def test_reverting_to_manual_clears_the_what_if(client):
    """Reverting is a statement about the whole academic source. A student
    who asks to enter their own numbers should not find a document still
    supplying one of them."""
    session_id = _confirmed_pair(client)
    _acknowledge(client, session_id)

    body = client.post(
        f"/audit/session/{session_id}/mode", params={"mode": "manual"}
    ).json()

    assert body["active_mode"] == "manual"
    assert body["documents"]["what_if"]["present"] is False
    assert body["documents"]["resolved"]["option_credits"] is None


def test_a_dormant_what_if_supplies_nothing_but_is_still_reported(
    what_if_record, majors
):
    """Removing a comparison option is not reverting. The document stays
    stored so an accidental removal doesn't cost a re-upload, and the payload
    reports it rather than leaving it invisible.

    Dormancy is expressed by the option simply not matching: resolution never
    consults a list of active options, so a stored document for a program
    nobody is comparing against contributes nothing by construction.
    """
    classification = classify_document(what_if_record, majors)
    resolved = resolve_comparison_inputs(
        None, what_if_record, classification, {}, acknowledged=True
    )
    # Still resolvable and still reported...
    assert resolved.option_credits is not None
    assert resolved.option_credits.program_key == "computer_science"
    # ...but it names exactly one program, so an option for any other major
    # receives nothing from it.
    assert classification.supplies_option_credits is True


def test_manual_values_are_preserved_for_restoration(what_if_record, majors):
    resolved = resolve_comparison_inputs(
        None,
        what_if_record,
        classify_document(what_if_record, majors),
        {"computer_science": 70, "psychology_ba": 45},
        acknowledged=True,
    )
    assert resolved.manual_restore == {"computer_science": 70, "psychology_ba": 45}


# --- Session separation -------------------------------------------------


def test_no_audit_route_assigns_comparison_inputs():
    """The audit session and the conversation session are separate stores
    with no link between them. Confirming a document must not mutate an
    already-calculated Ask Fork conversation -- the student applies the
    resolved values to the form and recalculates, which is what grounds it.
    """
    source = (Path(__file__).resolve().parent.parent / "main.py").read_text(
        encoding="utf-8"
    )
    audit_section = source[source.index('@app.post("/audit/unt/upload")') :]
    assert "set_inputs" not in audit_section