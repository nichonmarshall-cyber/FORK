"""
What a multi-option Change Major comparison is allowed to receive.

This sits one level above inputs.py. That file defines a single pairwise
calculation; this one defines a set of them sharing a baseline. The
student has one current major and one credit history, and they're weighing
several alternatives against it — so the shared facts live on
MultiComparisonInputs and the per-alternative facts live on each
ComparisonOption.

The important rule here: transferable credits are NOT a universal number.
72 completed credits might apply as 66 toward CS, 69 toward IT, and 54
toward Mechanical Engineering. Treating that as one figure across the
whole comparison would silently overstate or understate three different
paths at once, so every option carries its own.

Nothing in this file calculates anything. Its whole job is to turn a
multi-option request into a list of validated ChangeMajorInputs the
existing engine already knows how to run — and, where a value is missing,
to say WHICH option is missing WHICH field instead of guessing it.

Three sources eventually feed this same contract: the manual form, the AI
reading a student's sentence, and (later) a parsed degree audit. None of
them get to skip validation.
"""

from pydantic import BaseModel, Field, model_validator

from .inputs import ChangeMajorInputs

# Per-option fields the engine can't run without. credits_transferable is
# the only one: everything else either has a safe default or falls back to
# the institution's reference table. Kept as a named constant because both
# the completeness check and the "what should I ask the student for"
# message need to agree on exactly one list.
REQUIRED_OPTION_FIELDS = ("credits_transferable",)


class ComparisonOption(BaseModel):
    """
    One alternative major being weighed against the student's current one.

    credits_transferable is deliberately optional. A student naming three
    majors but only knowing the transfer figure for two isn't an error —
    it's an incomplete option, and Fork should run the two it can and ask
    about the third. None means "not supplied yet", never "zero transfer".
    """

    major: str = Field(
        ...,
        description="Key of the alternative major, matching a key in the "
                    "institution's 'majors' table (e.g. 'computer_science').",
    )
    credits_transferable: int | None = Field(
        default=None,
        ge=0,
        description="How many of the student's completed credits count "
                    "toward THIS major's degree. Option-specific — the same "
                    "72 completed credits apply differently to different "
                    "programs. None means not supplied yet.",
    )
    credits_transferable_source: str = Field(
        default="Student-reported",
        description="Where this option's transfer figure came from. A "
                    "what-if audit is reliable, a student's guess isn't, and "
                    "the result has to say which.",
    )
    prospective_credits_required: int | None = Field(
        default=None,
        ge=1,
        le=300,
        description="Total credits this major requires, when taken from an "
                    "audit rather than the reference table. Optional — "
                    "absent just means use the table value.",
    )
    prospective_credits_required_source: str | None = Field(
        default=None,
        description="Required whenever the override above is supplied.",
    )

    @model_validator(mode="after")
    def override_requires_a_source(self):
        """Same rule inputs.py enforces, checked here too so a bad option
        is caught while we still know which option it was. By the time it
        reaches ChangeMajorInputs the error message has lost the major
        name."""
        if self.prospective_credits_required is not None and not self.prospective_credits_required_source:
            raise ValueError(
                f"prospective_credits_required_source is required for "
                f"'{self.major}' whenever prospective_credits_required is "
                "supplied."
            )
        return self

    def missing_fields(self) -> list[str]:
        """Required fields this option still doesn't have. Empty list means
        it's ready to run."""
        return [f for f in REQUIRED_OPTION_FIELDS if getattr(self, f) is None]

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields()


class DuplicateOptionError(ValueError):
    """Raised when the same major appears twice with DIFFERENT values.

    Identical repeats get quietly collapsed — someone saying "CS, IT, CS"
    obviously wants CS once. But two entries for CS claiming different
    transfer figures is a real conflict, and picking one silently would
    put a number on screen the student never actually gave us.
    """


class MultiComparisonInputs(BaseModel):
    """
    The complete set of inputs for a multi-option comparison.

    Shared student facts at this level, per-alternative facts on each
    option. This is what both the form and the AI extraction layer produce,
    and it's the only thing the orchestration service accepts.
    """

    current_major: str = Field(
        ...,
        description="The student's ACTUAL current major. Always the anchor "
                    "every alternative is measured against — this decision "
                    "path has no notion of comparing majors from scratch "
                    "with no current one.",
    )
    credits_completed: int = Field(
        ...,
        ge=0,
        le=300,
        description="Credit hours completed and passed. A fact about the "
                    "student, not about any target major, so it lives here "
                    "rather than on each option.",
    )
    options: list[ComparisonOption] = Field(
        ...,
        description="The alternatives being weighed against current_major.",
    )

    # --- Provenance and optional shared values ---------------------------

    credits_source: str = Field(default="Student-reported")
    credits_source_date: str = Field(default="Not stated")
    credits_in_progress: int = Field(default=0, ge=0, le=30)

    @model_validator(mode="after")
    def drop_anchor_from_options(self):
        """
        A student comparing "Psychology, CS, and IT" while already majoring
        in Psychology is including their anchor in the list, which is
        completely natural phrasing. Psychology is still in the comparison
        — it's the baseline every alternative is measured against — so
        removing it from `options` isn't dropping it, it's just recognizing
        what it actually is.

        Letting it through would hit ChangeMajorInputs' majors_must_differ
        validator and blow up the entire comparison over a phrasing
        detail.
        """
        self.options = [o for o in self.options if o.major != self.current_major]
        return self

    @model_validator(mode="after")
    def collapse_duplicates(self):
        """Identical repeats collapse; conflicting ones raise. See
        DuplicateOptionError for why the two cases are treated
        differently."""
        seen: dict[str, ComparisonOption] = {}
        for option in self.options:
            existing = seen.get(option.major)
            if existing is None:
                seen[option.major] = option
            elif existing != option:
                raise DuplicateOptionError(
                    f"'{option.major}' was given twice with different values. "
                    "Fork won't pick one for you — send it once with the "
                    "values you mean."
                )
        self.options = list(seen.values())
        return self

    @model_validator(mode="after")
    def at_least_one_alternative(self):
        """Checked AFTER the anchor is dropped, so "compare me to myself"
        fails with a message about what actually went wrong rather than
        passing an empty fan-out down to the service."""
        if not self.options:
            raise ValueError(
                "A comparison needs at least one alternative major besides "
                f"'{self.current_major}'."
            )
        return self

    # --- Views the orchestration layer needs ------------------------------

    def ready_options(self) -> list[ComparisonOption]:
        """Options with everything the engine needs. These get calculated."""
        return [o for o in self.options if o.is_complete]

    def pending_options(self) -> list[ComparisonOption]:
        """Options still missing something. These get reported as pending
        so Fork can ask for the missing value — never estimated, never
        dropped from the comparison silently."""
        return [o for o in self.options if not o.is_complete]

    def option_for(self, major: str) -> ComparisonOption | None:
        return next((o for o in self.options if o.major == major), None)

    def all_majors(self) -> list[str]:
        """Everyone in the comparison, anchor first. This is the set
        `active_options` tracks — the anchor is part of the comparison, not
        outside it."""
        return [self.current_major] + [o.major for o in self.options]

    def to_pairwise_inputs(self, option: ComparisonOption) -> ChangeMajorInputs:
        """
        Build the validated pairwise input for one alternative.

        This is the seam: everything above is multi-option, everything
        below is the existing engine contract, unchanged. The engine never
        learns it's one of several runs.

        Deliberately lets ChangeMajorInputs' own validators fire rather
        than re-checking their rules here. transferable-can't-exceed-
        completed is defined in exactly one place, and the service catches
        the ValidationError per option so one bad figure marks that option
        failed instead of killing the whole comparison.
        """
        if not option.is_complete:
            raise ValueError(
                f"'{option.major}' is missing {', '.join(option.missing_fields())} "
                "— it can't be calculated yet. Check is_complete before calling this."
            )

        return ChangeMajorInputs(
            current_major=self.current_major,
            prospective_major=option.major,
            credits_completed=self.credits_completed,
            credits_transferable=option.credits_transferable,
            credits_source=self.credits_source,
            credits_transferable_source=option.credits_transferable_source,
            credits_source_date=self.credits_source_date,
            credits_in_progress=self.credits_in_progress,
            prospective_credits_required=option.prospective_credits_required,
            prospective_credits_required_source=option.prospective_credits_required_source,
        )
