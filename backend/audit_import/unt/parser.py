"""
UNT degree audit -> StudentAcademicRecord.

Understands the UNT audit *document format* and nothing about degrees. There
is no branch anywhere below on major, subject prefix, or course number, and
there should never be one: what a course satisfies is the matcher's question,
answered against a catalog, long after this file is done.

The pipeline:

    PDF bytes
        -> text (pypdf)
        -> chrome stripped, sections split
        -> header metadata
        -> canonical courses  (COURSES BY ACADEMIC YEAR)
        -> excluded attempts  (DUPLICATE COURSES)
        -> requirement placements, referencing courses by key
        -> reconciliation against the audit's stated totals

Nothing is written to disk. An audit carries a full grade history, and this
application has no authentication and no retention policy, so it doesn't keep
one.
"""

import io

from academic_record.models import StudentAcademicRecord
from academic_record.provenance import extracted, not_found

from .courses import parse_course_rows
from .header import parse_header
from .reconcile import reconcile
from .requirements import parse_requirements
from .text import AuditSections, strip_chrome

SOURCE_NAME = "UNT Degree Audit"


class UnsupportedDocument(Exception):
    """The file couldn't be read as a UNT degree audit.

    A real technical failure — unreadable file, wrong document, no text layer.
    Distinct from a document that parsed fine but left Fork unable to confirm
    something, which is not an error and must not be raised as one.
    """


def looks_like_unt_audit(lines: list[str]) -> bool:
    """Cheap structural check before committing to a full parse."""
    joined = "\n".join(lines[:60]).upper()
    signals = (
        "PREPARED ON" in joined and "CATALOG YEAR" in joined,
        "PROGRAM CODE" in joined,
        any("COURSES BY ACADEMIC YEAR" in line.upper() for line in lines),
    )
    return sum(bool(s) for s in signals) >= 2


def parse_audit_text(text: str) -> StudentAcademicRecord:
    """Text in, record out. No file access, no network, no model calls.

    Deterministic: the same text always produces the same record.
    """
    lines = strip_chrome(text)
    if not lines:
        raise UnsupportedDocument("The document contained no readable text.")
    if not looks_like_unt_audit(lines):
        raise UnsupportedDocument(
            "The document does not have the structure of a UNT degree audit."
        )

    sections = AuditSections(lines)
    header = parse_header(lines)

    record = StudentAcademicRecord(
        program=header.program,
        program_code=header.program_code,
        catalog_year=header.catalog_year,
        audit_prepared_at=header.audit_prepared_at,
        audit_evaluated_status=header.audit_evaluated_status,
        is_what_if=header.is_what_if,
    )
    record.warnings.extend(header.warnings)

    for field in ("program", "program_code", "catalog_year", "audit_prepared_at"):
        record.field_provenance[field] = (
            extracted(SOURCE_NAME) if getattr(record, field) is not None
            else not_found(SOURCE_NAME)
        )

    # Canonical courses. This section, and only this section, produces hours.
    if sections.has_canonical_course_section:
        record.courses = parse_course_rows(sections.by_academic_year, SOURCE_NAME)
    else:
        record.warnings.append(
            "No COURSES BY ACADEMIC YEAR section found. Without it there is no "
            "list in which each course appears exactly once, so no hour total "
            "can be established from this document."
        )

    # Excluded repeat attempts. UNT has already zeroed these and left them out
    # of the canonical listing; they are kept so the student's history is
    # complete and nothing looks quietly dropped.
    record.excluded_courses = parse_course_rows(sections.duplicate_courses, SOURCE_NAME)

    # Placements. These reference canonical courses by key and contribute no
    # hours of their own.
    record.requirements = parse_requirements(sections.requirement_analysis)

    known_keys = {course.key for course in record.courses}
    dangling = sum(
        1
        for requirement in record.requirements
        for placement in requirement.courses_applied
        if placement.course_key not in known_keys
    )
    if dangling:
        record.warnings.append(
            f"{dangling} requirement placement(s) referenced a course that is "
            "not in the canonical course list. Usually an excluded repeat "
            "attempt; worth checking if the count is large."
        )

    record.reconciliation = reconcile(record.courses, lines)
    if not record.reconciliation.reconciled:
        record.warnings.append(
            "Computed hours did not reconcile against the totals stated in the "
            f"document (computed {record.reconciliation.computed_completed_hours} "
            f"completed / {record.reconciliation.computed_in_progress_hours} in "
            f"progress; document stated {record.reconciliation.stated_completed_hours} "
            f"/ {record.reconciliation.stated_in_progress_hours}). Treat these "
            "figures as unconfirmed."
        )

    if record.is_what_if:
        record.warnings.append(
            "This document is a What-If audit. It describes a hypothetical "
            "program rather than the student's current standing."
        )

    return record


def parse_audit_pdf(file_bytes: bytes) -> StudentAcademicRecord:
    """Extract text from an audit PDF, then parse it.

    Bytes in, record out, bytes discarded. Nothing reaches disk.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise UnsupportedDocument("The file could not be read as a PDF.") from exc

    if not text.strip():
        raise UnsupportedDocument(
            "The PDF has no text layer, which usually means it's a scan or a "
            "photograph rather than a downloaded audit."
        )

    return parse_audit_text(text)