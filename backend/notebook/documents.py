"""
Documents in the student's record.

Two ways in, and they never blur:

  * A UNT degree audit or What-If audit the student has reviewed and confirmed
    through Fork's existing audit flow. Saving it copies a summary of what
    Fork read -- hours, program, catalog year, requirement counts -- and the
    facts that summary establishes into the notebook. The full course list
    stays in the short-lived audit session; the notebook keeps what Fork
    used, not the grade history.

  * A document the student records themselves (transcript, catalog page,
    advising notes). Fork hasn't read it and says so: status "recorded",
    no facts, nothing calculated from it.

Neither path claims anything was verified with the university.
"""

import threading
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from academic_record.enums import ExtractionStatus, RequirementStatus
from db.models import AcademicDocument, AcademicFact

from . import facts as F
from . import provenance as P
from . import timeline
from .storage import ALLOWED_CONTENT_TYPES, MAX_FILE_BYTES, StorageUnavailable, get_storage

# doc_type
DEGREE_AUDIT = "degree_audit"
WHAT_IF_AUDIT = "what_if_audit"
TRANSCRIPT = "transcript"
CATALOG = "catalog"
ADVISING_NOTE = "advising_note"
OTHER = "other"
RECORDABLE_TYPES = (TRANSCRIPT, CATALOG, ADVISING_NOTE, OTHER)

TYPE_LABELS = {
    DEGREE_AUDIT: "Degree audit",
    WHAT_IF_AUDIT: "What-If audit",
    TRANSCRIPT: "Transcript",
    CATALOG: "Catalog / degree requirements",
    ADVISING_NOTE: "Advising notes",
    OTHER: "Other academic document",
}

# source
PARSED_BY_FORK = "parsed_by_fork"
STUDENT_RECORDED = "student_recorded"

# status
CONFIRMED = "confirmed"
RECORDED = "recorded"
SUPERSEDED = "superseded"

STATUS_LABELS = {
    CONFIRMED: "Read by Fork, confirmed by you",
    RECORDED: "Recorded by you, not read by Fork",
    SUPERSEDED: "Replaced by a newer document",
}


class DocumentError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# An audit session id is a secret known only to the browser that uploaded the
# file. The first student to save one into their notebook claims it, so the
# same in-memory session can't then be pulled into a different account.
_claimed_audit_sessions: dict[str, str] = {}
_claim_lock = threading.Lock()


def _claim(audit_session_id: str, student_id: str) -> None:
    with _claim_lock:
        owner = _claimed_audit_sessions.setdefault(audit_session_id, student_id)
    if owner != student_id:
        raise DocumentError("That audit session belongs to a different account.", 403)


def reset_claims() -> None:
    with _claim_lock:
        _claimed_audit_sessions.clear()


# --- reading an audit record --------------------------------------------


def _requirement_counts(record) -> dict:
    counts = {status.value: 0 for status in RequirementStatus}
    for requirement in record.requirements:
        counts[requirement.status.value] += 1
    counts["total"] = len(record.requirements)
    return counts


def _degree_hours(record) -> dict | None:
    for requirement in record.requirements:
        if "TOTAL HOURS" in requirement.title.upper():
            if requirement.hours_earned is None and requirement.hours_needed is None:
                return None
            return {
                "earned": requirement.hours_earned,
                "needed": requirement.hours_needed,
                "in_progress": requirement.hours_in_progress,
            }
    return None


def _corrected_count(record) -> int:
    corrected = sum(
        1
        for course in record.courses
        if course.provenance.extraction_status == ExtractionStatus.STUDENT_CORRECTED
    )
    corrected += sum(
        1
        for p in record.field_provenance.values()
        if p.extraction_status == ExtractionStatus.STUDENT_CORRECTED
    )
    return corrected


def _audit_fingerprint(record, revision: int = 0) -> str:
    return "|".join(
        [
            str(record.audit_prepared_at),
            f"{record.completed_hours:g}",
            f"{record.in_progress_hours:g}",
            str(record.program),
            str(record.catalog_year),
            str(revision),
            str(_corrected_count(record)),
        ]
    )


def summarize_audit(record, majors: dict) -> dict:
    from documents.resolution import resolve_program_key

    reconciliation = record.reconciliation
    match = resolve_program_key(record, majors)
    return {
        "institution": record.institution,
        "completed_hours": round(record.completed_hours, 1),
        "in_progress_hours": round(record.in_progress_hours, 1),
        "totals_reconciled": bool(reconciliation and reconciliation.reconciled)
        if reconciliation
        else None,
        "stated_completed_hours": reconciliation.stated_completed_hours if reconciliation else None,
        "course_count": len(record.courses),
        "corrected_by_student": _corrected_count(record),
        "requirements": _requirement_counts(record),
        "degree_hours": _degree_hours(record),
        "program_match": match.model_dump(mode="json"),
        "warnings": list(record.warnings)[:10],
    }


def _audit_title(record, what_if: bool) -> str:
    kind = "What-If audit" if what_if else "Degree audit"
    if record.program:
        return f"UNT {kind} — {record.program}"[:200]
    return f"UNT {kind}"


# --- saving from the audit flow -----------------------------------------


def save_audit_from_session(
    db: Session,
    student_id: str,
    audit_session,
    which: str,
    majors: dict,
) -> tuple[AcademicDocument, bool]:
    """Copy a confirmed audit from the review session into the record.

    Returns (document, created). Saving the same confirmed reading twice
    returns the existing document rather than adding a duplicate and a second
    timeline line.
    """
    _claim(audit_session.session_id, student_id)

    if which == "what_if":
        return _save_what_if(db, student_id, audit_session, majors)
    if which != "current":
        raise DocumentError("Choose 'current' or 'what_if'.")
    return _save_current(db, student_id, audit_session, majors)


def _latest(db: Session, student_id: str, doc_type: str, program_key: str | None = None):
    query = select(AcademicDocument).where(
        AcademicDocument.student_id == student_id,
        AcademicDocument.doc_type == doc_type,
        AcademicDocument.status == CONFIRMED,
    )
    if program_key is not None:
        query = query.where(AcademicDocument.program_key == program_key)
    return list(db.scalars(query.order_by(AcademicDocument.created_at.desc())))


def _supersede(db: Session, documents: list[AcademicDocument]) -> list[str]:
    """Retire older documents and the facts they backed.

    The facts go too, not just get overwritten: a fact the new document
    doesn't establish must not keep citing the old one as though it were
    still current evidence.
    """
    ids = []
    for document in documents:
        document.status = SUPERSEDED
        ids.append(document.id)
        for fact in db.scalars(select(AcademicFact).where(AcademicFact.document_id == document.id)):
            db.delete(fact)
    db.flush()
    return ids


def _save_current(db, student_id, audit_session, majors):
    if not audit_session.has_confirmed_record:
        raise DocumentError(
            "Review and confirm the degree audit before adding it to your record.", 409
        )
    record = audit_session.uploaded_record
    fingerprint = _audit_fingerprint(record)

    previous = _latest(db, student_id, DEGREE_AUDIT)
    if previous and previous[0].summary.get("fingerprint") == fingerprint:
        return previous[0], False

    summary = summarize_audit(record, majors)
    summary["fingerprint"] = fingerprint
    match = summary["program_match"]
    program_key = match.get("program_key") if match.get("quality") == "exact" else None

    document = AcademicDocument(
        student_id=student_id,
        doc_type=DEGREE_AUDIT,
        title=_audit_title(record, what_if=False),
        source=PARSED_BY_FORK,
        status=CONFIRMED,
        institution_id="unt",
        program=record.program,
        program_key=program_key,
        catalog_year=record.catalog_year,
        document_date=record.audit_prepared_at,
        summary=summary,
        storage_status="not_stored",
    )
    db.add(document)
    db.flush()
    superseded = _supersede(db, previous)

    label = P.CONFIRMED_AUDIT_SOURCE
    when = record.audit_prepared_at or "Not stated"

    def doc_fact(key, value):
        F.put_fact(
            db,
            student_id,
            key,
            value,
            provenance=P.CONFIRMED_DOCUMENT,
            source_label=label,
            source_date=when,
            document_id=document.id,
        )

    # Whole hours, rounded the same way the existing adapter does, so the
    # notebook and the compare form can never show different figures for
    # the same confirmed audit.
    doc_fact(F.CREDITS_COMPLETED, round(record.completed_hours))
    doc_fact(F.CREDITS_IN_PROGRESS, round(record.in_progress_hours))
    if record.catalog_year:
        doc_fact(F.CATALOG_YEAR, record.catalog_year)
    if record.program:
        doc_fact(F.PROGRAM, record.program)
    doc_fact(F.REQUIREMENTS_SUMMARY, summary["requirements"])
    if summary["degree_hours"]:
        doc_fact(F.DEGREE_HOURS, summary["degree_hours"])

    replaced_major = None
    if program_key:
        existing = F.get_fact(db, student_id, F.CURRENT_MAJOR)
        if existing and existing.provenance == P.STUDENT_REPORTED:
            replaced_major = existing.value.get("value")
        doc_fact(F.CURRENT_MAJOR, program_key)

    completed = round(record.completed_hours)
    in_progress = round(record.in_progress_hours)
    timeline.record_event(
        db,
        student_id,
        timeline.AUDIT_ADDED,
        (
            f"Added your degree audit{f' for {record.program}' if record.program else ''}: "
            f"{completed} hours completed, {in_progress} in progress."
        ),
        detail={
            "completed_hours": completed,
            "in_progress_hours": in_progress,
            "catalog_year": record.catalog_year,
            "superseded_document_ids": superseded,
            "replaced_student_reported_major": replaced_major,
            "corrected_by_student": summary["corrected_by_student"],
        },
        document_id=document.id,
    )
    return document, True


def _save_what_if(db, student_id, audit_session, majors):
    from documents.resolution import classify_document, resolve_comparison_inputs

    stored = audit_session.what_if_document
    if stored is None or not stored.is_confirmed:
        raise DocumentError(
            "Review and confirm the What-If audit before adding it to your record.", 409
        )
    record = stored.record
    classification = classify_document(record, majors)
    program_key = classification.match.program_key if classification.supplies_option_credits else None
    fingerprint = _audit_fingerprint(record, stored.correction_revision)

    previous = _latest(db, student_id, WHAT_IF_AUDIT, program_key) if program_key else []
    if previous and previous[0].summary.get("fingerprint") == fingerprint:
        return previous[0], False
    if program_key is None:
        # An unmatched What-If supersedes nothing (there's no program to
        # say it replaces), but saving the same one twice still shouldn't
        # duplicate it.
        for existing in _latest(db, student_id, WHAT_IF_AUDIT):
            if existing.summary.get("fingerprint") == fingerprint:
                return existing, False

    # Same resolution the compare flow uses, so the notebook can't treat a
    # What-If as usable when the form would refuse it (an unacknowledged
    # disagreement, an unmatched program, no TOTAL HOURS block).
    current = audit_session.uploaded_record if audit_session.has_confirmed_record else None
    resolved = resolve_comparison_inputs(
        current,
        record,
        classification,
        audit_session.manual_transferable_by_major,
        acknowledged=audit_session.is_acknowledged(majors),
    )

    summary = summarize_audit(record, majors)
    summary["fingerprint"] = fingerprint
    summary["supplies_applicable_credits"] = resolved.option_credits is not None
    summary["unresolved"] = list(resolved.unresolved)
    if resolved.option_credits is not None:
        summary["applicable_credits"] = resolved.option_credits.credits_transferable

    document = AcademicDocument(
        student_id=student_id,
        doc_type=WHAT_IF_AUDIT,
        title=_audit_title(record, what_if=True),
        source=PARSED_BY_FORK,
        status=CONFIRMED,
        institution_id="unt",
        program=record.program,
        program_key=program_key,
        catalog_year=record.catalog_year,
        document_date=record.audit_prepared_at,
        summary=summary,
        storage_status="not_stored",
    )
    db.add(document)
    db.flush()
    superseded = _supersede(db, previous)

    if resolved.option_credits is not None:
        F.put_fact(
            db,
            student_id,
            F.APPLICABLE_CREDITS,
            resolved.option_credits.credits_transferable,
            provenance=P.WHAT_IF,
            source_label=resolved.option_credits.source,
            source_date=resolved.option_credits.source_date,
            document_id=document.id,
            scope=resolved.option_credits.program_key,
        )
        display = majors.get(program_key, {}).get("display_name", record.program or "that program")
        text = (
            f"Added a What-If audit for {display}: "
            f"{resolved.option_credits.credits_transferable} of your hours would apply."
        )
    else:
        text = (
            f"Added a What-If audit{f' for {record.program}' if record.program else ''}. "
            "Fork couldn't use it for applicable credits yet."
        )

    timeline.record_event(
        db,
        student_id,
        timeline.WHAT_IF_ADDED,
        text,
        detail={
            "program_key": program_key,
            "applicable_credits": summary.get("applicable_credits"),
            "unresolved": summary["unresolved"],
            "superseded_document_ids": superseded,
        },
        document_id=document.id,
    )
    return document, True


# --- documents the student records --------------------------------------


def record_document(
    db: Session,
    student_id: str,
    *,
    doc_type: str,
    title: str,
    document_date: str | None,
    note: str | None,
) -> AcademicDocument:
    if doc_type not in RECORDABLE_TYPES:
        raise DocumentError(
            "Degree audits are added through Fork's audit review so their figures "
            "can be checked. Choose transcript, catalog, advising notes, or other."
        )
    title = title.strip()
    if not title:
        raise DocumentError("Give the document a title.")
    if document_date:
        try:
            date.fromisoformat(document_date)
        except ValueError:
            raise DocumentError("Use a date like 2026-09-15.")

    document = AcademicDocument(
        student_id=student_id,
        doc_type=doc_type,
        title=title[:200],
        source=STUDENT_RECORDED,
        status=RECORDED,
        document_date=document_date,
        summary={},
        note=(note or "").strip()[:2000] or None,
        storage_status="not_stored",
    )
    db.add(document)
    db.flush()
    timeline.record_event(
        db,
        student_id,
        timeline.DOCUMENT_RECORDED,
        f"Recorded {document.title} ({TYPE_LABELS[doc_type].lower()}) in your record.",
        detail={"doc_type": doc_type},
        document_id=document.id,
    )
    return document


def attach_file(
    db: Session,
    student_id: str,
    document: AcademicDocument,
    data: bytes,
    content_type: str,
    filename: str | None,
) -> AcademicDocument:
    try:
        storage = get_storage()
    except StorageUnavailable as e:
        raise DocumentError(str(e), 503)
    if storage is None:
        raise DocumentError(
            "This deployment doesn't keep original files. Your document's details "
            "are saved; the file itself isn't.",
            501,
        )
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise DocumentError("Attach a PDF, PNG, JPEG, or plain-text file.", 415)
    if not data:
        raise DocumentError("That file was empty.")
    if len(data) > MAX_FILE_BYTES:
        raise DocumentError("That file is larger than the 10 MB limit.", 413)

    old_key = document.storage_key
    document.storage_key = storage.save(student_id, data, content_type)
    document.storage_status = "stored"
    document.original_filename = (filename or "document")[:255]
    document.content_type = content_type
    document.size_bytes = len(data)
    if old_key:
        storage.delete(old_key)

    timeline.record_event(
        db,
        student_id,
        timeline.DOCUMENT_FILE_ATTACHED,
        f"Attached the original file to {document.title}.",
        document_id=document.id,
    )
    return document


def remove_document(db: Session, student_id: str, document: AcademicDocument) -> None:
    """Remove a document and the facts it backed.

    Removing the latest confirmed audit does not resurrect an older,
    superseded one: an old audit is old evidence, and bringing it back
    silently would put stale hours on the dashboard. The student adds a
    current one instead.
    """
    title = document.title
    key = document.storage_key
    removed_facts = [
        f.key for f in db.scalars(select(AcademicFact).where(AcademicFact.document_id == document.id))
    ]
    db.delete(document)
    db.flush()
    timeline.record_event(
        db,
        student_id,
        timeline.DOCUMENT_REMOVED,
        f"Removed {title} from your record.",
        detail={"removed_facts": removed_facts},
    )
    if key:
        try:
            storage = get_storage()
            if storage is not None:
                storage.delete(key)
        except StorageUnavailable:
            pass


def list_documents(db: Session, student_id: str) -> list[AcademicDocument]:
    return list(
        db.scalars(
            select(AcademicDocument)
            .where(AcademicDocument.student_id == student_id)
            .order_by(AcademicDocument.created_at.desc())
        )
    )


def get_owned_document(db: Session, student_id: str, document_id: str) -> AcademicDocument:
    """Another student's document is reported exactly like a missing one, so
    ids can't be probed for existence."""
    document = db.get(AcademicDocument, document_id)
    if document is None or document.student_id != student_id:
        raise DocumentError("That document isn't in your record.", 404)
    return document


def serialize_document(document: AcademicDocument, facts: list[AcademicFact]) -> dict:
    linked = [F.serialize_fact(f) for f in facts if f.document_id == document.id]
    return {
        "id": document.id,
        "doc_type": document.doc_type,
        "type_label": TYPE_LABELS.get(document.doc_type, document.doc_type),
        "title": document.title,
        "source": document.source,
        "status": document.status,
        "status_label": STATUS_LABELS.get(document.status, document.status),
        "read_by_fork": document.source == PARSED_BY_FORK,
        "institution_id": document.institution_id,
        "program": document.program,
        "program_key": document.program_key,
        "catalog_year": document.catalog_year,
        "document_date": document.document_date,
        "summary": {k: v for k, v in (document.summary or {}).items() if k != "fingerprint"},
        "note": document.note,
        "file": {
            "stored": document.storage_status == "stored",
            "filename": document.original_filename,
            "content_type": document.content_type,
            "size_bytes": document.size_bytes,
        },
        "linked_facts": linked,
        "added_at": F._iso(document.created_at),
    }
