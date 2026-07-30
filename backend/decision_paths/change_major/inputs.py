"""
Defines what the Change Major engine is allowed to receive.

This is the boundary between unstructured input — someone typing a
sentence, a PDF audit — and the math. The engine never sees raw text or PDF
bytes, only a validated instance of this class.

Every credit figure carries a source string with it: "Student-reported",
"Degree audit, parsed 2026-07-29", and so on. The engine copies that into
the result so the provenance panel can tell someone whether a number came
from their registrar or from their own estimate. A figure with no stated
origin shouldn't be in the system.
"""

from pydantic import BaseModel, Field, field_validator, model_validator


class ChangeMajorInputs(BaseModel):
    """The complete set of inputs required to run a projection."""

    current_major: str = Field(
        ...,
        description="Key of the student's current major, matching a key in "
                    "the reference data's 'majors' table (e.g. 'computer_science').",
    )
    prospective_major: str = Field(
        ...,
        description="Key of the major the student is considering switching to.",
    )
    credits_completed: int = Field(
        ...,
        ge=0,
        le=300,
        description="Credit hours completed and passed. Courses in progress "
                    "are not included here.",
    )
    credits_transferable: int = Field(
        ...,
        ge=0,
        description="How many completed credits count toward the new DEGREE — "
                    "including any that apply only as elective hours rather "
                    "than satisfying a major requirement. Switching within a "
                    "field usually carries most credits over, so this is often "
                    "close to credits_completed. Reliable only from a what-if "
                    "audit or an advisor; anything else is an estimate.",
    )

    # --- Provenance -----------------------------------------------------

    credits_source: str = Field(
        default="Student-reported",
        description="Where credits_completed came from. Set to the audit name "
                    "when parsed from one.",
    )
    credits_transferable_source: str = Field(
        default="Student-reported",
        description="Where credits_transferable came from. A what-if audit is "
                    "reliable, a student estimate is not, and the result needs "
                    "to say which one it was.",
    )
    credits_source_date: str = Field(
        default="Not stated",
        description="Date these credit figures were accurate as of, usually "
                    "the audit run date.",
    )

    # --- Optional values from an uploaded audit --------------------------
    # These belong to a single request. Do not merge them into the reference
    # JSON: that file is meant to be a stable, citable dataset, while an
    # audit belongs to one student at one point in time.

    credits_in_progress: int = Field(
        default=0,
        ge=0,
        le=30,
        description="Hours currently in progress. Display only, never counted "
                    "as completed — a course still underway hasn't been earned.",
    )
    prospective_credits_required: int | None = Field(
        default=None,
        ge=1,
        le=300,
        description="Total credits the new major requires, when taken from an "
                    "audit rather than the reference table. Takes precedence "
                    "over the table value.",
    )
    prospective_credits_required_source: str | None = Field(
        default=None,
        description="Required whenever the override above is supplied.",
    )

    @field_validator("credits_transferable")
    @classmethod
    def transferable_cannot_exceed_completed(cls, v, info):
        completed = info.data.get("credits_completed")
        if completed is not None and v > completed:
            raise ValueError(
                "credits_transferable cannot exceed credits_completed "
                f"(got {v} transferable vs {completed} completed)."
            )
        return v

    @model_validator(mode="after")
    def majors_must_differ(self):
        """This was previously an empty stub that documented the rule without
        checking it. Now enforced. The engine still guards the same case,
        but catching it here lets the AI layer ask a follow-up question
        instead of the request reaching the engine at all."""
        if self.current_major == self.prospective_major:
            raise ValueError(
                "current_major and prospective_major must differ — "
                f"both were '{self.current_major}'."
            )
        return self

    @model_validator(mode="after")
    def override_requires_a_source(self):
        """An override without a citation renders in the UI as an
        authoritative figure with nothing behind it. Reject it."""
        if self.prospective_credits_required is not None and not self.prospective_credits_required_source:
            raise ValueError(
                "prospective_credits_required_source is required whenever "
                "prospective_credits_required is supplied."
            )
        return self


class MissingInputs(Exception):
    """Raised when there isn't enough information yet to build valid inputs.
    Carries the list of missing fields so the caller can ask a specific
    follow-up rather than a generic "I didn't understand that"."""

    def __init__(self, missing_fields: list[str]):
        self.missing_fields = missing_fields
        super().__init__(f"Missing required inputs: {', '.join(missing_fields)}")
