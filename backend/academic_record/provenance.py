"""
Where a value came from, kept as structure rather than prose.

The existing engine carries provenance as a single string ("Student-reported",
"Degree audit, parsed 2026-07-29"). That works when there are two
possibilities. It stops working the moment a student edits one field of a
parsed audit, because the resulting value is neither purely from UNT nor
purely from the student, and any single string describing it is misleading in
one direction or the other.

So provenance here is a small object. Rendering it back down to a string for
the engine is a formatting decision made at the boundary, and `describe()`
does it in a way that cannot claim UNT as the source of something the student
typed.
"""

from pydantic import BaseModel, Field

from .enums import ExtractionStatus


class FieldProvenance(BaseModel):
    """Origin of a single value in the record."""

    source: str = Field(
        default="UNT Degree Audit",
        description="The document this value was read from.",
    )
    extraction_status: ExtractionStatus = ExtractionStatus.EXTRACTED
    confirmed_by_student: bool = False
    original_value: str | None = Field(
        default=None,
        description="What the document said, when the student has changed it. "
                    "Kept so a correction can be shown alongside what it "
                    "replaced, and so an accidental edit can be walked back.",
    )
    note: str | None = Field(
        default=None,
        description="Why this value is the way it is, when that isn't obvious. "
                    "Internal; not written for students to read.",
    )

    def corrected(self, original_value: str) -> "FieldProvenance":
        """Return provenance for a value the student has just changed.

        Only the first correction records an original — editing twice should
        still show what UNT said, not the student's previous attempt.
        """
        already_corrected = (
            self.extraction_status == ExtractionStatus.STUDENT_CORRECTED
        )
        return FieldProvenance(
            source=self.source,
            extraction_status=ExtractionStatus.STUDENT_CORRECTED,
            confirmed_by_student=self.confirmed_by_student,
            original_value=self.original_value if already_corrected else original_value,
            note=self.note,
        )

    def describe(self) -> str:
        """A one-line description safe to show a student or hand to the engine.

        Never renders a student-edited value as though UNT supplied it. This is
        the function that keeps a corrected figure from being cited as
        registrar data downstream.
        """
        if self.extraction_status == ExtractionStatus.STUDENT_ADDED:
            return "Added by you"
        if self.extraction_status == ExtractionStatus.STUDENT_CORRECTED:
            return f"{self.source}, corrected by you"
        if self.extraction_status == ExtractionStatus.NOT_FOUND:
            return f"Not found in {self.source}"
        if self.confirmed_by_student:
            return f"{self.source}, confirmed by you"
        return self.source


def extracted(source: str = "UNT Degree Audit", note: str | None = None) -> FieldProvenance:
    return FieldProvenance(source=source, note=note)


def not_found(source: str = "UNT Degree Audit", note: str | None = None) -> FieldProvenance:
    return FieldProvenance(
        source=source, extraction_status=ExtractionStatus.NOT_FOUND, note=note
    )