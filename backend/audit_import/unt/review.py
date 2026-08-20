"""
Turning a parsed record into something a student can check.

The confirmation step asks one question — does this match your academic
record? — so the answer has to be checkable at a glance. Showing 36 course rows
against a 6-page PDF and asking someone to diff them is not a review, it's a
chore they will click through.

So the summary leads with the few figures that would be obviously wrong if the
parser had misread something: total hours, hours in progress, the program, the
catalog year. A student knows roughly how many hours they have. If Fork says 81
and they think 60, they'll notice, and that single mismatch catches most parse
failures that matter.

Language rules, applied here because this is where student-facing strings are
built:

  * Never "verified". Fork read a document and asked whether it read it right.
  * A parser diagnostic is not a student-facing message. Warnings stay in the
    record for debugging; what surfaces here is written for a person.
  * Not being able to confirm something is not an error, and doesn't get error
    styling or apologetic phrasing.
"""

from pydantic import BaseModel, Field

from academic_record.enums import CompletionStatus
from academic_record.models import StudentAcademicRecord


class ReviewCourse(BaseModel):
    key: str
    course_code: str
    title: str | None
    hours: float
    grade: str | None
    term: str | None
    status: str
    status_label: str
    note: str | None = None
    source_label: str


class Checkpoint(BaseModel):
    """One figure for the student to check at a glance.

    Structured rather than a rendered sentence so the UI can lay these out —
    a program name and an hour count want different treatment, and deciding
    which is which by inspecting the string would be guesswork.
    """

    key: str
    label: str
    value: str
    kind: str = Field(
        description="'text' or 'hours'. What sort of value this is, so the UI "
                    "can align, unit-format, or emphasise without parsing.",
    )
    unit: str | None = None


class ReviewSummary(BaseModel):
    """What Fork will show the student to confirm."""

    program: str | None
    catalog_year: str | None
    prepared_at: str | None
    is_what_if: bool
    completed_hours: float
    in_progress_hours: float
    course_count: int
    headline: str
    checkpoints: list[Checkpoint]
    notices: list[str]
    totals_confirmed: bool
    courses: list[ReviewCourse]
    excluded_courses: list[ReviewCourse]


_STATUS_LABELS = {
    CompletionStatus.COMPLETED: "Completed",
    CompletionStatus.IN_PROGRESS: "In progress",
    CompletionStatus.ATTEMPTED_NO_CREDIT: "No credit earned",
    CompletionStatus.NOT_COUNTED: "Not counted toward hours",
    CompletionStatus.UNKNOWN: "Can't confirm",
}

_STATUS_NOTES = {
    CompletionStatus.IN_PROGRESS: "Counted separately from your completed hours.",
    CompletionStatus.NOT_COUNTED: "A later attempt at this course is the one that counts.",
    CompletionStatus.UNKNOWN: "We found this course but couldn't read how it turned out.",
}


def _to_review_course(course) -> ReviewCourse:
    return ReviewCourse(
        key=course.key,
        course_code=course.course_code,
        title=course.title,
        hours=course.hours,
        grade=course.grade,
        term=course.term_label or course.term_code,
        status=course.completion_status.value,
        status_label=_STATUS_LABELS.get(course.completion_status, "Can't confirm"),
        note=_STATUS_NOTES.get(course.completion_status),
        source_label=course.provenance.describe(),
    )


def build_review(record: StudentAcademicRecord) -> ReviewSummary:
    """Assemble the confirmation view for a parsed record."""
    reconciliation = record.reconciliation
    totals_confirmed = bool(reconciliation and reconciliation.reconciled)

    # Ordered by how quickly a student would spot an error. Someone knows their
    # program instantly and their hour count roughly; the catalog year is the
    # one most will have to think about, so it goes last.
    checkpoints: list[Checkpoint] = []
    if record.program:
        checkpoints.append(
            Checkpoint(key="program", label="Program", value=record.program, kind="text")
        )
    checkpoints.append(
        Checkpoint(
            key="completed_hours",
            label="Hours completed",
            value=f"{record.completed_hours:g}",
            kind="hours",
            unit="hours",
        )
    )
    checkpoints.append(
        Checkpoint(
            key="in_progress_hours",
            label="Hours in progress",
            value=f"{record.in_progress_hours:g}",
            kind="hours",
            unit="hours",
        )
    )
    if record.catalog_year:
        checkpoints.append(
            Checkpoint(
                key="catalog_year",
                label="Catalog year",
                value=record.catalog_year,
                kind="text",
            )
        )

    notices: list[str] = []

    if not totals_confirmed:
        # The parser and the document disagree. Say so in the terms a student
        # can act on — check the numbers — without exposing which internal
        # check failed.
        notices.append(
            "The hours we added up don't match the totals printed on your "
            "audit, so please check the numbers below carefully before "
            "confirming."
        )

    if record.is_what_if:
        notices.append(
            "This looks like a What-If audit, which shows a program you were "
            "exploring rather than the one you're currently in. You can still "
            "use it, but check that the program below is the right one."
        )

    unknown = [
        c for c in record.courses if c.completion_status == CompletionStatus.UNKNOWN
    ]
    if unknown:
        notices.append(
            f"We couldn't tell how {len(unknown)} course"
            f"{'s' if len(unknown) != 1 else ''} turned out. "
            "They aren't included in any total — you can correct them below."
        )

    if record.excluded_courses:
        notices.append(
            f"{len(record.excluded_courses)} repeated course"
            f"{'s are' if len(record.excluded_courses) != 1 else ' is'} listed "
            "separately. Your audit counts only the most recent attempt, and so "
            "do we."
        )

    missing = [
        field
        for field in ("program", "catalog_year")
        if getattr(record, field) is None
    ]
    if missing:
        notices.append(
            "We couldn't read your program and catalog year from this "
            "document. You can fill them in below."
            if len(missing) == 2
            else "We couldn't read your "
            + ("program" if missing[0] == "program" else "catalog year")
            + " from this document. You can fill it in below."
        )

    return ReviewSummary(
        program=record.program,
        catalog_year=record.catalog_year,
        prepared_at=record.audit_prepared_at,
        is_what_if=record.is_what_if,
        completed_hours=record.completed_hours,
        in_progress_hours=record.in_progress_hours,
        course_count=len(record.courses),
        headline="Here's what we read from your audit. Does this match your "
                 "academic record?",
        checkpoints=checkpoints,
        notices=notices,
        totals_confirmed=totals_confirmed,
        courses=[_to_review_course(c) for c in record.courses],
        excluded_courses=[_to_review_course(c) for c in record.excluded_courses],
    )