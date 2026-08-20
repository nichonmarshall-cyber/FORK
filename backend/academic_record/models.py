"""
The normalized academic record: facts about what a student has taken.

This model deliberately knows nothing about degrees. It does not decide that
CSCE 2100 satisfies Foundations of Computing, that 81 hours is enough, or that
a catalog year is supported. It records what a document said, in a shape the
matcher can reason about later.

Two structural rules make the hour totals trustworthy:

  1. `courses` is canonical and each course appears exactly once. In a UNT
     audit the same course is printed two or three times — under its
     requirement, under major residency, and under COURSES BY ACADEMIC YEAR.
     Only the last of those is read as a course; the rest are placements.

  2. `requirements[].courses_applied` holds keys into `courses`, never course
     objects. A requirement cannot contribute hours, only point at them, so
     no arrangement of requirement parsing can inflate a total.
"""

from pydantic import BaseModel, Field, computed_field

from .enums import (
    NON_COUNTING_SPECIAL_CODES,
    ArticulationType,
    CompletionStatus,
    RequirementStatus,
    SpecialCode,
)
from .provenance import FieldProvenance, extracted


class NormalizedCourse(BaseModel):
    """One course, as the document reported it."""

    subject: str = Field(description="Subject prefix, e.g. 'CSCE'.")
    number: str = Field(description="Course number as printed, e.g. '2100' or "
                                    "'1000Z'. A string, because the trailing "
                                    "letter is part of the number.")
    title: str | None = Field(
        default=None,
        description="UNT's abbreviated title ('FDNS DATA STRUCTURES'), not the "
                    "catalog title. Fine to display; not reliable for matching.",
    )
    hours: float = 0.0
    grade: str | None = None
    term_code: str | None = Field(
        default=None,
        description="Raw UNT term code, e.g. '26.8'. Stored as printed.",
    )
    term_label: str | None = Field(
        default=None,
        description="Decoded term, e.g. 'Fall 2026'. The mapping "
                    "(.1 Spring, .4 Summer, .8 Fall) is inferred from observed "
                    "data rather than documented by UNT, so this is a "
                    "convenience for display and nothing depends on it.",
    )
    source_institution: str | None = Field(
        default=None,
        description="None means UNT. Neither reference document contains "
                    "transfer coursework, so this has never been populated "
                    "from a real export.",
    )
    completion_status: CompletionStatus = CompletionStatus.UNKNOWN
    special_code: SpecialCode | None = None
    articulation_type: ArticulationType = ArticulationType.NOT_APPLICABLE
    provenance: FieldProvenance = Field(default_factory=extracted)
    raw_line: str | None = Field(
        default=None,
        description="The line this was parsed from. Kept for debugging and to "
                    "show a student the source of anything that looks wrong.",
    )

    @computed_field
    @property
    def key(self) -> str:
        """Stable identifier used by requirement placements and by the
        correction API. Includes the term so two attempts at the same course
        remain distinguishable."""
        return f"{self.term_code or '?'}:{self.subject}{self.number}"

    @computed_field
    @property
    def course_code(self) -> str:
        return f"{self.subject} {self.number}"

    @property
    def counts_toward_earned_hours(self) -> bool:
        if self.special_code in NON_COUNTING_SPECIAL_CODES:
            return False
        return self.completion_status == CompletionStatus.COMPLETED


class RequirementPlacement(BaseModel):
    """A course the audit showed under a requirement.

    Holds a key, not a course. This is what stops requirement parsing from
    double-counting hours.
    """

    course_key: str
    advisor_applied: bool = Field(
        default=False,
        description="Set when the audit shows an advisor placed this course by "
                    "hand. Student-specific evidence the matcher must preserve "
                    "rather than re-derive. Never yet seen in a real export.",
    )
    raw_line: str | None = None


class Subrequirement(BaseModel):
    """A numbered item within a requirement block.

    Delimited by the trailing `1)` / `OR)` marker UNT prints after each item's
    content, which makes these boundaries structural rather than inferred —
    unlike the enclosing block, whose start is guessed from formatting.

    `label` is empty for content that appeared before the first numbered item.
    `OR` marks an alternative path rather than a sequential requirement.
    """

    label: str = ""
    description: str | None = None
    courses_applied: list["RequirementPlacement"] = Field(default_factory=list)
    remaining_rule: str | None = None
    raw_lines: list[str] = Field(default_factory=list)

    @property
    def is_alternative(self) -> bool:
        return self.label.upper() == "OR"


class AuditRequirement(BaseModel):
    """One requirement block from the audit.

    Best-effort. Block boundaries in the printer-friendly export are inferred
    from formatting rather than marked, so `header_confidence` records how
    solid the boundary looked and `raw_lines` keeps the evidence. Nothing about
    hour totals depends on this parsing being right.
    """

    title: str
    status: RequirementStatus = RequirementStatus.UNKNOWN
    courses_applied: list[RequirementPlacement] = Field(default_factory=list)
    subrequirements: list[Subrequirement] = Field(
        default_factory=list,
        description="Numbered items within the block. Segmented on UNT's "
                    "trailing number markers, so these boundaries are reliable "
                    "even where the block's own start was inferred.",
    )
    hours_earned: float | None = None
    hours_needed: float | None = None
    hours_in_progress: float | None = None
    subrequirements_earned: int | None = None
    subrequirements_needed: int | None = None
    remaining_rule: str | None = Field(
        default=None,
        description="A SELECT FROM line, verbatim. Recorded, never "
                    "interpreted — deciding what satisfies it is the matcher's "
                    "job and needs the catalog.",
    )
    advisor_application: str | None = None
    header_confidence: str = Field(
        default="medium",
        description="high | medium | low. How confident the block boundary is.",
    )
    raw_lines: list[str] = Field(default_factory=list)
    status_evidence: list[str] = Field(
        default_factory=list,
        description="The marker lines the status was derived from. UNT's OK / "
                    "NO / + / - glyphs are absent from this export, so the "
                    "derivation needs to be inspectable.",
    )


class Reconciliation(BaseModel):
    """Parser self-check against the totals the audit states about itself.

    The audit prints its own EARNED and IN PROGRESS figures. Summing the
    canonical course list must reproduce them. When it doesn't, the parser
    misread something, and the record says so instead of quietly serving a
    wrong number.
    """

    computed_completed_hours: float
    computed_in_progress_hours: float
    stated_completed_hours: float | None = None
    stated_in_progress_hours: float | None = None
    tolerance: float = 0.05

    @computed_field
    @property
    def completed_matches(self) -> bool | None:
        if self.stated_completed_hours is None:
            return None
        return abs(self.computed_completed_hours - self.stated_completed_hours) <= self.tolerance

    @computed_field
    @property
    def in_progress_matches(self) -> bool | None:
        if self.stated_in_progress_hours is None:
            return None
        return abs(self.computed_in_progress_hours - self.stated_in_progress_hours) <= self.tolerance

    @computed_field
    @property
    def reconciled(self) -> bool:
        """True only when both figures were found and both agree.

        Deliberately false when the stated totals are missing. An unverified
        total is not a verified one, and the caller should treat it the same
        way — carefully.
        """
        return self.completed_matches is True and self.in_progress_matches is True


class StudentAcademicRecord(BaseModel):
    """Everything Fork read from a student's academic document."""

    # --- Document metadata ---
    program: str | None = None
    program_code: str | None = None
    catalog_year: str | None = Field(
        default=None,
        description="Exactly as printed, e.g. 'Fall 2024'. Not normalized to a "
                    "catalog range here — mapping a term to a catalog is the "
                    "resolver's job, and it needs to be able to say it has no "
                    "requirements for a given year.",
    )
    audit_prepared_at: str | None = None
    audit_evaluated_status: str | None = Field(
        default=None,
        description="The audit's own summary line, e.g. 'AT LEAST ONE "
                    "REQUIREMENT IS NOT YET SATISFIED'.",
    )
    is_what_if: bool = Field(
        default=False,
        description="True when the export is marked NOT FINALIZED. A What-If "
                    "describes a hypothetical program, so it is never treated "
                    "as a statement of the student's actual standing.",
    )
    institution: str = "University of North Texas"
    document_type: str = "unt_degree_audit"

    # --- Academic content ---
    courses: list[NormalizedCourse] = Field(default_factory=list)
    requirements: list[AuditRequirement] = Field(default_factory=list)
    excluded_courses: list[NormalizedCourse] = Field(
        default_factory=list,
        description="Attempts UNT excluded from credit — the RX rows under "
                    "DUPLICATE COURSES. Kept so a student can see their repeat "
                    "history, and so nothing appears to have been dropped. "
                    "Never contributes hours.",
    )

    # --- Parser diagnostics ---
    reconciliation: Reconciliation | None = None
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    warnings: list[str] = Field(
        default_factory=list,
        description="Internal diagnostics. Not student-facing copy.",
    )

    @computed_field
    @property
    def completed_hours(self) -> float:
        return round(
            sum(c.hours for c in self.courses if c.counts_toward_earned_hours), 1
        )

    @computed_field
    @property
    def in_progress_hours(self) -> float:
        return round(
            sum(
                c.hours
                for c in self.courses
                if c.completion_status == CompletionStatus.IN_PROGRESS
            ),
            1,
        )

    def course_by_key(self, key: str) -> NormalizedCourse | None:
        return next((c for c in self.courses if c.key == key), None)

    @property
    def parsed_anything(self) -> bool:
        return bool(self.courses)