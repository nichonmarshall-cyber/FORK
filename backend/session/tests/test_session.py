"""
Session tests: the review-correct-confirm gate, and mode exclusivity.

The parser proves Fork can read a document. These prove a document Fork has
read doesn't become calculation input until the student says it's right, and
that manual entry and a confirmed upload never supply values at the same time.
"""

from pathlib import Path

import pytest

from academic_record.enums import (
    AcademicInputMode,
    CompletionStatus,
    ConfirmationStatus,
    ExtractionStatus,
)
from audit_import.unt.parser import parse_audit_text
from audit_import.unt.review import build_review
from session.context import CorrectionRequest, SessionAcademicContext
from session.store import AcademicSessionStore, SessionNotFound

FIXTURES = Path(__file__).resolve().parents[2] / "audit_import/unt/tests/fixtures"


@pytest.fixture
def record():
    return parse_audit_text((FIXTURES / "unt_audit_standard.txt").read_text())


@pytest.fixture
def session(record):
    context = SessionAcademicContext(session_id="test")
    context.attach_record(record)
    return context


# --- The confirmation gate ---------------------------------------------


def test_upload_does_not_activate_the_record(session):
    """Parsing is not confirming. A record Fork has read but the student hasn't
    checked stays inert, and the session stays in manual."""
    assert session.mode == AcademicInputMode.MANUAL
    assert session.confirmation_status == ConfirmationStatus.AWAITING_REVIEW
    assert session.has_confirmed_record is False


def test_confirmation_activates_the_record(session):
    session.confirm()
    assert session.mode == AcademicInputMode.CONFIRMED_UPLOAD
    assert session.confirmation_status == ConfirmationStatus.CONFIRMED
    assert session.has_confirmed_record is True


def test_cannot_confirm_without_a_record():
    empty = SessionAcademicContext(session_id="empty")
    with pytest.raises(ValueError):
        empty.confirm()


def test_correction_after_confirmation_reopens_review(session):
    """Confirmation covers the values that were shown. Changing one afterwards
    would leave the session claiming agreement to something never seen."""
    session.confirm()
    assert session.confirmation_status == ConfirmationStatus.CONFIRMED

    session.apply_correction(CorrectionRequest(field="catalog_year", value="Fall 2025"))

    assert session.confirmation_status == ConfirmationStatus.AWAITING_REVIEW
    assert session.has_confirmed_record is False


# --- Corrections and provenance ----------------------------------------


def test_corrected_course_is_not_described_as_coming_from_unt(session):
    """The central provenance rule: a value the student typed must never be
    presented as something the registrar supplied."""
    course = session.uploaded_record.courses[0]
    original_hours = course.hours

    outcome = session.apply_correction(
        CorrectionRequest(field="hours", value=4.0, course_key=course.key)
    )

    assert outcome.applied is True
    assert course.hours == 4.0
    assert course.provenance.extraction_status == ExtractionStatus.STUDENT_CORRECTED
    assert course.provenance.original_value == str(original_hours)
    assert "corrected by you" in course.provenance.describe()
    assert course.provenance.describe() != "UNT Degree Audit"


def test_editing_twice_still_shows_the_documents_value(session):
    """The original is what UNT said, not the student's previous attempt."""
    course = session.uploaded_record.courses[0]
    documented = str(course.hours)

    session.apply_correction(CorrectionRequest(field="hours", value=4.0, course_key=course.key))
    session.apply_correction(CorrectionRequest(field="hours", value=5.0, course_key=course.key))

    assert course.provenance.original_value == documented


def test_correcting_a_document_field_records_provenance(session):
    session.apply_correction(CorrectionRequest(field="catalog_year", value="Fall 2025"))

    assert session.uploaded_record.catalog_year == "Fall 2025"
    provenance = session.uploaded_record.field_provenance["catalog_year"]
    assert provenance.original_value == "Fall 2024"
    assert "corrected by you" in provenance.describe()


def test_correction_changes_the_totals_it_should(session):
    """An edit has to actually move the derived figures, or the review step is
    theatre."""
    before = session.uploaded_record.completed_hours
    completed = next(
        c for c in session.uploaded_record.courses
        if c.completion_status == CompletionStatus.COMPLETED
    )
    session.apply_correction(
        CorrectionRequest(field="hours", value=completed.hours + 1, course_key=completed.key)
    )
    assert session.uploaded_record.completed_hours == before + 1


def test_uneditable_fields_are_rejected(session):
    """Totals are derived from coursework. Editing the total instead of the
    courses behind it produces a record that matches no real transcript."""
    outcome = session.apply_correction(CorrectionRequest(field="completed_hours", value=99))
    assert outcome.applied is False
    assert "cannot be edited" in (outcome.message or "")


def test_unknown_course_rejected(session):
    outcome = session.apply_correction(
        CorrectionRequest(field="hours", value=3.0, course_key="99.9:NOPE0000")
    )
    assert outcome.applied is False


def test_confirmation_marks_provenance_confirmed(session):
    session.confirm()
    assert all(c.provenance.confirmed_by_student for c in session.uploaded_record.courses)
    assert "confirmed by you" in session.uploaded_record.courses[0].provenance.describe()


# --- Mode exclusivity --------------------------------------------------


def test_switching_to_manual_clears_the_uploaded_record(session):
    """The clearing is the point. A confirmed record left in place while manual
    values drive the calculation is how two sources end up competing."""
    session.confirm()
    session.switch_to_manual()

    assert session.mode == AcademicInputMode.MANUAL
    assert session.uploaded_record is None
    assert session.confirmation_status is None
    assert session.degree_match_results is None
    assert session.has_confirmed_record is False


def test_exactly_one_active_source(session):
    assert session.mode == AcademicInputMode.MANUAL
    session.confirm()
    assert session.mode == AcademicInputMode.CONFIRMED_UPLOAD
    assert session.uploaded_record is not None
    session.switch_to_manual()
    assert session.mode == AcademicInputMode.MANUAL
    assert session.uploaded_record is None


def test_uploaded_source_is_reported_separately_from_active_mode(session):
    """A parsed record awaiting review exists while manual is still active.

    That state is invisible to any client that derives one fact from the other,
    and it is the whole of the review step.
    """
    state = session.uploaded_source
    assert state.present is True
    assert state.awaiting_review is True
    assert state.is_active is False
    assert session.mode == AcademicInputMode.MANUAL

    session.confirm()
    state = session.uploaded_source
    assert state.is_active is True
    assert state.awaiting_review is False

    session.switch_to_manual()
    assert session.uploaded_source.present is False


def test_active_source_never_claims_verification(session):
    """Fork checked its own reading against the student. It did not check
    anything with UNT, and no student-facing string may suggest otherwise."""
    assert "verif" not in session.active_source_description.lower()
    session.confirm()
    assert session.active_source_description == "the academic information you confirmed"
    assert "verif" not in session.active_source_description.lower()


# --- The store ---------------------------------------------------------


def test_store_round_trip():
    store = AcademicSessionStore()
    created = store.create()
    assert store.get(created.session_id) is created


def test_unknown_session_raises():
    store = AcademicSessionStore()
    with pytest.raises(SessionNotFound):
        store.get("nope")


def test_expired_sessions_are_swept():
    """An audit is an education record. One shouldn't sit in memory because a
    tab was left open."""
    from datetime import timedelta

    store = AcademicSessionStore(ttl=timedelta(seconds=-1))
    created = store.create()
    with pytest.raises(SessionNotFound):
        store.get(created.session_id)


def test_store_capacity_is_bounded():
    store = AcademicSessionStore(max_sessions=3)
    for _ in range(10):
        store.create()
    assert store.count() <= 3


def test_session_ids_are_unguessable():
    store = AcademicSessionStore()
    ids = {store.create().session_id for _ in range(50)}
    assert len(ids) == 50
    assert all(len(i) >= 16 for i in ids)


# --- The review view ---------------------------------------------------


def test_review_leads_with_checkable_figures(record):
    """A student knows roughly how many hours they have. That single number
    catches most parse failures worth catching."""
    review = build_review(record)
    assert review.completed_hours == 81.0
    assert review.in_progress_hours == 18.0

    by_key = {c.key: c for c in review.checkpoints}
    assert by_key["completed_hours"].value == "81"
    assert by_key["completed_hours"].kind == "hours"
    assert by_key["program"].kind == "text"
    assert by_key["catalog_year"].value == "Fall 2024"
    assert review.totals_confirmed is True


def test_review_hides_internal_diagnostics(record):
    """Parser vocabulary is not student-facing copy."""
    review = build_review(record)
    text = review.model_dump_json().lower()
    for term in ("reconcil", "traceback", "regex", "parser", "unsupporteddocument", "none"):
        assert term not in text.replace('"none"', "")


def test_review_explains_repeated_courses_plainly(record):
    review = build_review(record)
    assert review.excluded_courses
    assert any("repeated course" in n for n in review.notices)
    assert all("RX" not in c.status_label for c in review.excluded_courses)


def test_review_flags_a_what_if_document():
    whatif = parse_audit_text((FIXTURES / "unt_audit_whatif.txt").read_text())
    review = build_review(whatif)
    assert review.is_what_if is True
    assert any("What-If" in n for n in review.notices)


def test_review_asks_for_confirmation_not_verification(record):
    review = build_review(record)
    assert "match your academic record" in review.headline
    assert "verif" not in review.model_dump_json().lower()


def test_unreconciled_record_asks_the_student_to_look_closer():
    """Failing to reconcile is not an error state and doesn't read like one —
    it asks for attention rather than reporting a fault."""
    text = (FIXTURES / "unt_audit_standard.txt").read_text()
    lines = text.split("\n")
    marker = next(i for i, l in enumerate(lines) if "COURSES BY ACADEMIC YEAR" in l)
    broken = parse_audit_text(
        "\n".join(l for i, l in enumerate(lines) if not (i > marker and "CSCE1030" in l))
    )

    review = build_review(broken)
    assert review.totals_confirmed is False
    notice = next(n for n in review.notices if "don't match" in n)
    assert "error" not in notice.lower()
    assert "failed" not in notice.lower()