"""
Vocabulary for the normalized academic record.

Each of these is a fact about what a document said, never a judgement about
degree progress. Whether CSCE 2100 satisfies a requirement is the matcher's
call; all this layer records is that the course exists, carries three hours,
and was passed with a C.

Where a value could not be determined, the enum says so explicitly. UNKNOWN,
UNEVALUATED, and NOT_APPLICABLE are three different statements and are never
used interchangeably — see the note on each.
"""

from enum import Enum


class CompletionStatus(str, Enum):
    """Whether a course produced credit, from the document's point of view."""

    COMPLETED = "completed"
    """Finished, passed, hours earned."""

    IN_PROGRESS = "in_progress"
    """Currently enrolled. Never counted as completed, regardless of how
    likely the student is to pass — the audit itself keeps these separate and
    so do we."""

    ATTEMPTED_NO_CREDIT = "attempted_no_credit"
    """Finished without earning hours: F, W, NP. Recorded rather than dropped,
    so a failed course doesn't silently vanish between the PDF and the
    record."""

    NOT_COUNTED = "not_counted"
    """Excluded from credit by a repeat or duplication rule, not by the grade.
    See SpecialCode."""

    UNKNOWN = "unknown"
    """The row parsed, but its status could not be read. Distinct from
    ATTEMPTED_NO_CREDIT: that one means we know no credit was earned, this one
    means we don't know either way. Never counted in any total."""


class SpecialCode(str, Enum):
    """Repeat and duplication codes as UNT prints them.

    Where one of these bears on whether hours count, it takes precedence over
    the grade. A row reading `0.0 F RX ALGEBRA` is excluded because of the RX,
    and would still be excluded if the grade were an A.
    """

    IN_PROGRESS = "IP"
    REPEATABLE = ">R"
    REPEAT_EXCLUDE = "RX"
    DUPLICATION = "DP"
    REPEAT_COUNT = "RC"


#: Codes that suppress earned hours no matter what grade sits next to them.
NON_COUNTING_SPECIAL_CODES = frozenset(
    {SpecialCode.REPEAT_EXCLUDE, SpecialCode.DUPLICATION}
)

#: Codes observed in a real UNT audit export, with their formatting confirmed.
#: RX and RC appear in the reference documents; IP appears as the second token
#: of an `EN IP` pair. DP and >R are supported from UNT's documented behaviour
#: but their printed formatting has NOT been seen in a real export, so any
#: fixture exercising them is synthetic. Do not describe DP or >R handling as
#: format-validated until a real example turns up.
FORMAT_VALIDATED_SPECIAL_CODES = frozenset(
    {SpecialCode.IN_PROGRESS, SpecialCode.REPEAT_EXCLUDE, SpecialCode.REPEAT_COUNT}
)


class ArticulationType(str, Enum):
    """How a transfer course was mapped onto a UNT requirement.

    Neither reference document contains transfer coursework, so none of the
    transfer-specific values below have been seen in a real export. They are
    modelled because the record needs somewhere to put the information, not
    because the parser can currently produce them. A UNT-native course gets
    NOT_APPLICABLE.
    """

    DIRECT_MATCH = "direct_match"
    SUBJECT_AREA_INDIRECT = "subject_area_indirect"
    STANDARD_INDIRECT = "standard_indirect"
    UNMAPPED = "unmapped"
    UNEVALUATED = "unevaluated"
    """Transfer credit that UNT has accepted but not yet articulated."""

    ADVISOR_APPLIED = "advisor_applied"
    """An advisor placed this course by hand. Student-specific evidence — the
    matcher preserves it rather than re-deriving it."""

    NOT_APPLICABLE = "not_applicable"
    """Taken at UNT, so there is nothing to articulate. Distinct from
    UNEVALUATED, which means transfer work awaiting a decision."""


class RequirementStatus(str, Enum):
    """Whether a requirement block is satisfied.

    UNT's web interface marks these OK / IP / NO / + / -, but those glyphs do
    not survive the printer-friendly PDF export. These values are derived from
    the EARNED / NEEDS / IN PROGRESS / IP HOURS markers that do survive, and
    every requirement keeps the raw lines the derivation came from.
    """

    COMPLETE = "complete"
    IN_PROGRESS = "in_progress"
    UNFULFILLED = "unfulfilled"
    UNKNOWN = "unknown"
    """No marker was found. The requirement was read but its state could not
    be determined — not the same as unfulfilled."""


class AcademicInputMode(str, Enum):
    """Which academic source is active for a session. Exactly one at a time."""

    MANUAL = "manual"
    CONFIRMED_UPLOAD = "confirmed_upload"


class ConfirmationStatus(str, Enum):
    """Where an uploaded record sits in the review flow."""

    AWAITING_REVIEW = "awaiting_review"
    CONFIRMED = "confirmed"


class ExtractionStatus(str, Enum):
    """Whether a value still reads as the document produced it."""

    EXTRACTED = "extracted"
    STUDENT_CORRECTED = "student_corrected"
    STUDENT_ADDED = "student_added"
    NOT_FOUND = "not_found"