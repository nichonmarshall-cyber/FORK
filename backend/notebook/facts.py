"""
Academic facts and the rules for changing them.

The one rule that matters most: a student-reported value never silently
replaces a figure backed by a confirmed document. If the student's audit says
72 hours and they type 80, the honest options are to add a newer audit or to
remove the old one -- not to have the notebook quietly show 80 as though the
document said so, or 72 as though they hadn't spoken. The service refuses the
edit and says why.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import AcademicFact

from . import provenance as P

# Fact keys. Every value is stored as {"value": ...}.
CURRENT_MAJOR = "current_major"
PROGRAM = "program"
CATALOG_YEAR = "catalog_year"
GPA = "gpa"
CREDITS_COMPLETED = "credits_completed"
CREDITS_IN_PROGRESS = "credits_in_progress"
APPLICABLE_CREDITS = "applicable_credits"  # scoped to a major key
REQUIREMENTS_SUMMARY = "requirements_summary"
DEGREE_HOURS = "degree_hours"

#: Facts a student may set or clear themselves.
STUDENT_EDITABLE = (CURRENT_MAJOR, GPA, CREDITS_COMPLETED, CREDITS_IN_PROGRESS, CATALOG_YEAR)

_FACT_NAMES = {
    CURRENT_MAJOR: "current major",
    GPA: "GPA",
    CREDITS_COMPLETED: "completed credits",
    CREDITS_IN_PROGRESS: "credits in progress",
    CATALOG_YEAR: "catalog year",
}


class FactConflict(ValueError):
    """A student edit that would overwrite a document-backed figure."""

    def __init__(self, key: str, message: str):
        super().__init__(message)
        self.key = key


def get_facts(db: Session, student_id: str) -> list[AcademicFact]:
    return list(
        db.scalars(
            select(AcademicFact)
            .where(AcademicFact.student_id == student_id)
            .order_by(AcademicFact.key, AcademicFact.scope)
        )
    )


def get_fact(db: Session, student_id: str, key: str, scope: str = "") -> AcademicFact | None:
    return db.scalar(
        select(AcademicFact).where(
            AcademicFact.student_id == student_id,
            AcademicFact.key == key,
            AcademicFact.scope == scope,
        )
    )


def put_fact(
    db: Session,
    student_id: str,
    key: str,
    value,
    *,
    provenance: str,
    source_label: str,
    source_date: str | None = None,
    document_id: str | None = None,
    scope: str = "",
) -> AcademicFact:
    if provenance not in P.ALL:
        raise ValueError(f"Unknown provenance '{provenance}'.")
    fact = get_fact(db, student_id, key, scope)
    if fact is None:
        fact = AcademicFact(student_id=student_id, key=key, scope=scope)
        db.add(fact)
    fact.value = {"value": value}
    fact.provenance = provenance
    fact.source_label = source_label
    fact.source_date = source_date
    fact.document_id = document_id
    fact.updated_at = datetime.now(timezone.utc)
    return fact


def delete_fact(db: Session, student_id: str, key: str, scope: str = "") -> bool:
    fact = get_fact(db, student_id, key, scope)
    if fact is None:
        return False
    db.delete(fact)
    return True


def apply_student_edits(
    db: Session, student_id: str, edits: dict[str, object]
) -> list[tuple[str, object, object]]:
    """Set or clear student-reported facts. Returns (key, old, new) for each
    value that actually changed.

    Validated as a whole before anything is written, so a refused field
    leaves the rest of the batch unapplied rather than half-saved.
    """
    for key in edits:
        if key not in STUDENT_EDITABLE:
            raise ValueError(f"'{key}' can't be edited directly.")
        existing = get_fact(db, student_id, key)
        if existing is not None and existing.provenance != P.STUDENT_REPORTED:
            current = existing.value.get("value")
            if edits[key] == current:
                continue
            raise FactConflict(
                key,
                f"Your {_FACT_NAMES[key]} comes from {existing.source_label}. "
                "To change it, add a newer document or remove that one from "
                "your record -- Fork won't put your own figure in place of a "
                "document's without that.",
            )

    changes: list[tuple[str, object, object]] = []
    for key, new_value in edits.items():
        existing = get_fact(db, student_id, key)
        old_value = existing.value.get("value") if existing else None
        if existing is not None and existing.provenance != P.STUDENT_REPORTED:
            continue  # unchanged document-backed value, checked above
        if new_value is None:
            if existing is not None:
                db.delete(existing)
                changes.append((key, old_value, None))
            continue
        if old_value == new_value:
            continue
        put_fact(
            db,
            student_id,
            key,
            new_value,
            provenance=P.STUDENT_REPORTED,
            source_label="Entered by you",
        )
        changes.append((key, old_value, new_value))
    return changes


def serialize_fact(fact: AcademicFact) -> dict:
    return {
        "key": fact.key,
        "scope": fact.scope or None,
        "value": fact.value.get("value"),
        "provenance": fact.provenance,
        "provenance_label": P.LABELS[fact.provenance],
        "source_label": fact.source_label,
        "source_date": fact.source_date,
        "document_id": fact.document_id,
        "updated_at": _iso(fact.updated_at),
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
