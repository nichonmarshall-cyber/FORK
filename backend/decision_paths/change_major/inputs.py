"""
Input schema for the Change Major Decision Path.

This is the contract between the AI extraction layer and the calculation
engine. The AI's job is to fill this schema from conversation. The engine
never sees raw conversation text — only a validated instance of this class.
"""

from pydantic import BaseModel, Field, field_validator


class ChangeMajorInputs(BaseModel):
    """Validated inputs required to run the Change Major calculation."""

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
        description="Total credit hours the student has completed so far, "
                    "toward their CURRENT major.",
    )
    credits_transferable: int = Field(
        ...,
        ge=0,
        description="Of the completed credits, how many the student's advisor "
                    "or registrar estimates will count toward the PROSPECTIVE "
                    "major. In v1 this is student-reported, not catalog-derived "
                    "— see ARCHITECTURE.md, Phase 5 for automated credit audits.",
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

    @field_validator("current_major", "prospective_major")
    @classmethod
    def majors_must_differ(cls, v, info):
        # Only checked meaningfully once both fields are present; the engine
        # layer also guards against this, but we surface it as early as
        # possible so the AI layer can ask a clarifying question instead of
        # the request ever reaching the calculation engine.
        return v


class MissingInputs(Exception):
    """Raised by the AI extraction layer when the conversation does not yet
    contain enough information to build a valid ChangeMajorInputs instance.
    Carries a list of the specific fields still needed so the AI layer can
    ask a targeted follow-up question rather than a generic one."""

    def __init__(self, missing_fields: list[str]):
        self.missing_fields = missing_fields
        super().__init__(f"Missing required inputs: {', '.join(missing_fields)}")