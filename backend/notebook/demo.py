"""
The demo notebook: one fictional student, a year of academic history.

For a portfolio visitor to click through without signing up. Everything
here is made up -- the student, the documents, the dates -- and the UI says
so on every page. What is NOT made up is the arithmetic: every saved
comparison is computed by the real engine from the inputs listed, at the
moment the demo is built, so the demo can never show a figure the product
wouldn't.

The record is rebuilt from this file whenever the app starts, so it can't
drift and nothing a visitor does persists (every write is refused anyway;
see accounts.auth.require_writable).

The story: Jordan, a Computer Science student, wonders about switching in
the fall, gets serious about Business Administration in the spring once a
degree audit and a What-If are in hand, leans toward switching, then -- with
a newer audit, a better GPA, and an advisor meeting -- decides to stay.
"""

import os
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from accounts.passwords import hash_password
from db.models import AcademicDocument, AcademicFact, SavedScenario, Student, TimelineEvent

from . import facts as F
from . import provenance as P
from . import scenarios as S
from . import timeline as T

#: Not a registrable address -- registration requires a dot after the "@" --
#: so no real account can ever collide with the demo.
DEMO_EMAIL = "demo-student@fork"
DEMO_NAME = "Jordan (demo)"

AUDIT_SOURCE = P.CONFIRMED_AUDIT_SOURCE
WHAT_IF_SOURCE = (
    "UNT What-If Audit — Bachelor of Business Administration, Fall 2025, confirmed by you"
)


def demo_enabled() -> bool:
    return os.environ.get("FORK_DEMO", "true").strip().lower() not in ("0", "false", "no", "off")


def at(text: str) -> datetime:
    """'2026-03-04 15:20' (Central time) as an aware UTC datetime."""
    from zoneinfo import ZoneInfo

    local = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("America/Chicago"))
    return local.astimezone(timezone.utc)


def ensure_demo_student(db: Session) -> Student:
    student = db.scalar(select(Student).where(Student.is_demo.is_(True)))
    if student is None:
        student = build_demo(db)
    return student


def rebuild_demo(db: Session) -> Student:
    """Delete and rebuild the demo record. Run at startup."""
    for existing in db.scalars(select(Student).where(Student.is_demo.is_(True))):
        db.delete(existing)
    db.flush()
    student = build_demo(db)
    db.commit()
    return student


# --- builders -----------------------------------------------------------


class _Builder:
    def __init__(self, db: Session, student: Student, reference: dict):
        self.db = db
        self.student = student
        self.reference = reference

    def event(self, when, event_type, summary, detail=None, document=None, scenario=None):
        self.db.add(
            TimelineEvent(
                student_id=self.student.id,
                event_type=event_type,
                summary=summary,
                detail=detail or {},
                document_id=document.id if document else None,
                scenario_id=scenario.id if scenario else None,
                occurred_at=at(when),
            )
        )

    def document(self, when, **fields) -> AcademicDocument:
        doc = AcademicDocument(
            student_id=self.student.id,
            storage_status="not_stored",
            created_at=at(when),
            updated_at=at(when),
            **fields,
        )
        self.db.add(doc)
        self.db.flush()
        return doc

    def fact(self, when, key, value, provenance, source, source_date=None, document=None, scope=""):
        fact = F.put_fact(
            self.db,
            self.student.id,
            key,
            value,
            provenance=provenance,
            source_label=source,
            source_date=source_date,
            document_id=document.id if document else None,
            scope=scope,
        )
        fact.updated_at = at(when)
        return fact

    def retire(self, document: AcademicDocument):
        document.status = "superseded"
        for fact in self.db.scalars(
            select(AcademicFact).where(AcademicFact.document_id == document.id)
        ):
            self.db.delete(fact)
        self.db.flush()

    def scenario(self, when, title, completed, in_progress, options) -> SavedScenario:
        """`completed` is (value, provenance, source, source_date, document);
        each option is (major, value, provenance, source, source_date, document)."""
        value, prov, source, source_date, doc = completed
        inputs = {
            "current_major": "computer_science",
            "credits_completed": {
                "value": value,
                "provenance": prov,
                "source_label": source,
                "source_date": source_date,
                "document_id": doc.id if doc else None,
            },
            "credits_in_progress": in_progress,
            "options": [
                {
                    "major": major,
                    "credits_transferable": transfer,
                    "provenance": o_prov,
                    "source_label": o_source,
                    "source_date": o_date,
                    "document_id": o_doc.id if o_doc else None,
                }
                for major, transfer, o_prov, o_source, o_date, o_doc in options
            ],
        }
        outcome = S.calculate(inputs, self.reference)
        scenario = SavedScenario(
            student_id=self.student.id,
            title=title,
            kind=S.KIND,
            current_major="computer_science",
            inputs=inputs,
            outcome=outcome,
            calculated_at=at(when),
            created_at=at(when),
            updated_at=at(when),
        )
        self.db.add(scenario)
        self.db.flush()
        return scenario


def _audit_summary(completed, in_progress, needed, complete_blocks, total_blocks, courses, gpa=None, read_at=None):
    return {
        "read_at": at(read_at).isoformat() if read_at else None,
        "file_kept": False,
        "institution": "University of North Texas",
        "completed_hours": float(completed),
        "in_progress_hours": float(in_progress),
        "totals_reconciled": True,
        "stated_completed_hours": float(completed),
        "course_count": courses,
        "corrected_by_student": 0,
        "requirements": {
            "complete": complete_blocks,
            "in_progress": 2,
            "unfulfilled": total_blocks - complete_blocks - 2,
            "unknown": 0,
            "total": total_blocks,
        },
        "degree_hours": {"earned": float(completed), "needed": float(needed), "in_progress": float(in_progress)},
        "program_match": {"quality": "exact", "program_key": "computer_science", "candidates": [], "reason": None},
        "gpa": gpa,
        "warnings": [],
        "demo": True,
    }


def _gpa(value, hours, points):
    """A GPA block as a UNT audit states it. Values chosen so points/hours
    truncates to the printed GPA, the same check real audits must pass."""
    assert int(points / hours * 1000) / 1000 == value
    return {"cumulative_gpa": value, "attempted_hours": hours, "quality_points": points, "reconciled": True, "note": None}



def build_demo(db: Session) -> Student:
    from data_loading.loader import build_reference_data

    reference = build_reference_data("unt")
    student = Student(
        email=DEMO_EMAIL,
        # A random secret nobody holds: there is no way to sign in to the
        # demo with a password, only through POST /account/demo.
        password_hash=hash_password(secrets.token_urlsafe(32)),
        display_name=DEMO_NAME,
        institution_id="unt",
        is_demo=True,
        created_at=at("2025-08-25 19:12"),
    )
    db.add(student)
    db.flush()
    b = _Builder(db, student, reference)

    # Fall 2025 -- just curious --------------------------------------------
    b.event("2025-08-25 19:12", T.NOTEBOOK_STARTED, "Started your Fork notebook.")

    b.fact("2025-09-08 21:40", F.CURRENT_MAJOR, "computer_science", P.STUDENT_REPORTED, "Entered by you")
    b.fact("2025-09-08 21:40", F.CREDITS_COMPLETED, 45, P.STUDENT_REPORTED, "Entered by you")
    b.event(
        "2025-09-08 21:40",
        T.FACTS_UPDATED,
        "You set your current major to Computer Science; set your completed credits to 45 (your own figures).",
    )

    s1 = b.scenario(
        "2025-09-10 22:05",
        "Compared Computer Science with Information Technology",
        (45, P.STUDENT_REPORTED, P.STUDENT_SOURCE, None, None),
        0,
        [("information_technology", 42, P.STUDENT_REPORTED, P.STUDENT_SOURCE, None, None)],
    )
    b.event("2025-09-10 22:05", T.COMPARISON_SAVED, f"Saved a comparison: {s1.title}.", scenario=s1)

    # Spring 2026 -- getting serious ---------------------------------------
    audit1 = b.document(
        "2026-01-20 14:32",
        doc_type="degree_audit",
        title="UNT Degree audit — Bachelor of Science in Computer Science",
        source="parsed_by_fork",
        status="confirmed",
        institution_id="unt",
        program="Bachelor of Science in Computer Science",
        program_key="computer_science",
        catalog_year="Fall 2024",
        document_date="01/16/2026 09:41 AM",
        summary=_audit_summary(60, 15, 60, 5, 14, 22, _gpa(3.214, 63.0, 202.5), "2026-01-20 14:31"),
    )
    for key, value in (
        (F.CURRENT_MAJOR, "computer_science"),
        (F.PROGRAM, "Bachelor of Science in Computer Science"),
        (F.CATALOG_YEAR, "Fall 2024"),
        (F.CREDITS_COMPLETED, 60),
        (F.CREDITS_IN_PROGRESS, 15),
        (F.GPA, 3.214),
    ):
        b.fact("2026-01-20 14:32", key, value, P.CONFIRMED_DOCUMENT, AUDIT_SOURCE, "01/16/2026 09:41 AM", audit1)
    b.event(
        "2026-01-20 14:32",
        T.AUDIT_ADDED,
        "Added your degree audit for Bachelor of Science in Computer Science: 60 hours completed, 15 in progress, GPA 3.214.",
        detail={"replaced_student_reported_major": "computer_science"},
        document=audit1,
    )

    s2 = b.scenario(
        "2026-02-12 16:47",
        "Compared Computer Science with Business Administration (BBA) and Psychology (B.A.)",
        (60, P.CONFIRMED_DOCUMENT, AUDIT_SOURCE, "01/16/2026 09:41 AM", audit1),
        15,
        [
            ("business_administration", 48, P.STUDENT_REPORTED, P.STUDENT_SOURCE, None, None),
            ("psychology_ba", 51, P.STUDENT_REPORTED, P.STUDENT_SOURCE, None, None),
        ],
    )
    b.event("2026-02-12 16:47", T.COMPARISON_SAVED, f"Saved a comparison: {s2.title}.", scenario=s2)

    what_if = b.document(
        "2026-03-04 11:09",
        doc_type="what_if_audit",
        title="UNT What-If audit — Bachelor of Business Administration",
        source="parsed_by_fork",
        status="confirmed",
        institution_id="unt",
        program="Bachelor of Business Administration",
        program_key="business_administration",
        catalog_year="Fall 2025",
        document_date="03/03/2026 04:55 PM",
        summary={
            **_audit_summary(60, 15, 66, 4, 13, 22, None, "2026-03-04 11:08"),
            "program_match": {
                "quality": "exact",
                "program_key": "business_administration",
                "candidates": [],
                "reason": None,
            },
            "supplies_applicable_credits": True,
            "applicable_credits": 54,
            "unresolved": [],
        },
    )
    b.fact(
        "2026-03-04 11:09",
        F.APPLICABLE_CREDITS,
        54,
        P.WHAT_IF,
        WHAT_IF_SOURCE,
        "03/03/2026 04:55 PM",
        what_if,
        scope="business_administration",
    )
    b.event(
        "2026-03-04 11:09",
        T.WHAT_IF_ADDED,
        "Added a What-If audit for Business Administration (BBA): 54 of your hours would apply.",
        detail={"program_key": "business_administration", "applicable_credits": 54},
        document=what_if,
    )

    s3 = b.scenario(
        "2026-03-05 18:26",
        "Compared Computer Science with Business Administration (BBA), using the What-If",
        (60, P.CONFIRMED_DOCUMENT, AUDIT_SOURCE, "01/16/2026 09:41 AM", audit1),
        15,
        [("business_administration", 54, P.WHAT_IF, WHAT_IF_SOURCE, "03/03/2026 04:55 PM", what_if)],
    )
    b.event("2026-03-05 18:26", T.COMPARISON_SAVED, f"Saved a comparison: {s3.title}.", scenario=s3)
    b.event(
        "2026-03-20 13:02",
        T.PLAN_CHOSEN,
        "Marked switching to Business Administration (BBA) as your current plan.",
        detail={"decision": "business_administration", "stay": False},
        scenario=s3,
    )

    advising = b.document(
        "2026-04-15 10:44",
        doc_type="advising_note",
        title="Advising appointment — Spring 2026",
        source="student_recorded",
        status="recorded",
        document_date="2026-04-15",
        summary={},
        note=(
            "Asked whether CSCE 3110 counts toward BBA electives. Advisor suggested "
            "finishing spring grades before deciding and running a new audit in August."
        ),
    )
    b.event(
        "2026-04-15 10:44",
        T.DOCUMENT_RECORDED,
        "Recorded Advising appointment — Spring 2026 (advising notes) in your record.",
        document=advising,
    )

    # Fall 2026 -- deciding -------------------------------------------------
    audit2 = b.document(
        "2026-08-19 15:51",
        doc_type="degree_audit",
        title="UNT Degree audit — Bachelor of Science in Computer Science",
        source="parsed_by_fork",
        status="confirmed",
        institution_id="unt",
        program="Bachelor of Science in Computer Science",
        program_key="computer_science",
        catalog_year="Fall 2024",
        document_date="08/14/2026 02:17 PM",
        summary=_audit_summary(75, 15, 45, 7, 14, 27, _gpa(3.339, 78.0, 260.5), "2026-08-19 15:50"),
    )
    b.retire(audit1)
    for key, value in (
        (F.CURRENT_MAJOR, "computer_science"),
        (F.PROGRAM, "Bachelor of Science in Computer Science"),
        (F.CATALOG_YEAR, "Fall 2024"),
        (F.CREDITS_COMPLETED, 75),
        (F.CREDITS_IN_PROGRESS, 15),
        (F.REQUIREMENTS_SUMMARY, audit2.summary["requirements"]),
        (F.DEGREE_HOURS, audit2.summary["degree_hours"]),
        (F.GPA, 3.339),
    ):
        b.fact("2026-08-19 15:51", key, value, P.CONFIRMED_DOCUMENT, AUDIT_SOURCE, "08/14/2026 02:17 PM", audit2)
    b.event(
        "2026-08-19 15:51",
        T.AUDIT_ADDED,
        "Added your degree audit for Bachelor of Science in Computer Science: 75 hours completed, 15 in progress, GPA 3.339.",
        detail={"superseded_document_ids": [audit1.id]},
        document=audit2,
    )

    s4 = b.scenario(
        "2026-09-02 19:14",
        "Compared Computer Science with Information Technology and Business Administration (BBA)",
        (75, P.CONFIRMED_DOCUMENT, AUDIT_SOURCE, "08/14/2026 02:17 PM", audit2),
        15,
        [
            ("information_technology", 72, P.STUDENT_REPORTED, P.STUDENT_SOURCE, None, None),
            ("business_administration", 54, P.WHAT_IF, WHAT_IF_SOURCE, "03/03/2026 04:55 PM", what_if),
        ],
    )
    b.event("2026-09-02 19:14", T.COMPARISON_SAVED, f"Saved a comparison: {s4.title}.", scenario=s4)

    s4.decision = "computer_science"
    b.event(
        "2026-09-10 12:30",
        T.PLAN_CHOSEN,
        "Marked staying in Computer Science as your current plan.",
        detail={"decision": "computer_science", "stay": True},
        scenario=s4,
    )
    # Choosing a plan clears the earlier one (one plan at a time).
    s3.decision = None

    db.flush()
    return student
