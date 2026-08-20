"""
Confirmed academic record -> Change Major engine inputs.

The narrowest possible bridge. It supplies the two figures a degree audit
actually establishes and refuses to supply the one it doesn't.

`credits_completed` and `credits_in_progress` come straight off the confirmed
record: the audit states both, the parser reconciles its own arithmetic against
the audit's stated totals, and the student has confirmed the reading. Those are
defensible.

`credits_transferable` is not. The engine documents it as credits counting
toward the new *degree*, electives included. Establishing that number needs a
course-by-course match against the destination program's requirements, and Fork
has no matcher. The nearby temptations are all wrong:

  * passing `credits_completed` assumes everything transfers,
  * passing some fraction invents a rule nobody wrote down,
  * passing 0 asserts nothing transfers, which is worse than either.

So the adapter reports it as unavailable, with the reason attached, and the
student supplies their own estimate. That keeps one honest number beside one
acknowledged estimate rather than two numbers of unmarked quality.

When a matcher exists, this file is where it plugs in, and the `unavailable`
entry disappears on its own.
"""

from pydantic import BaseModel, Field

SOURCE_LABEL = "UNT Degree Audit, confirmed by you"


class UnavailableInput(BaseModel):
    """An engine input the confirmed record cannot supply.

    Carries both a `reason_code` for tests and logs and a `user_message`
    written for a student, because the two audiences need different words and
    collapsing them means one of them gets the wrong ones.
    """

    field: str
    reason_code: str
    technical_detail: str
    user_message: str


class ConfirmedRecordInputs(BaseModel):
    """What a confirmed audit contributes to a Change Major calculation.

    Deliberately partial. Absent fields are absent because the record does not
    establish them, and a caller merging this over its own state will leave
    those fields as the student entered them.
    """

    credits_completed: int
    credits_in_progress: int
    credits_source: str = SOURCE_LABEL
    credits_source_date: str = "Not stated"
    catalog_year: str | None = None
    program: str | None = None
    totals_confirmed: bool = False
    unavailable: list[UnavailableInput] = Field(default_factory=list)


def _transferable_unavailable(prospective_label: str | None = None) -> UnavailableInput:
    target = prospective_label or "your prospective major"
    return UnavailableInput(
        field="credits_transferable",
        reason_code="requires_course_level_matching",
        technical_detail=(
            "credits_transferable is degree-applicable hours including "
            "electives. Deriving it requires matching each completed course "
            "against the destination program's requirements, which needs a "
            "catalog specification and a matcher. Neither exists yet."
        ),
        user_message=(
            f"Fork can't work out how many of these hours count toward {target} "
            "from your degree audit alone — that needs a course-by-course "
            "check against the program's requirements, which Fork doesn't do "
            "yet. Enter the figure from a What-If audit, or your best estimate."
        ),
    )


def build_inputs_from_confirmed_record(
    session, prospective_label: str | None = None
) -> ConfirmedRecordInputs | None:
    """Read engine inputs off a confirmed session. None if nothing is confirmed.

    Returning None rather than raising: an unconfirmed session is an ordinary
    state during review, not an error, and the caller asks this question on
    every session fetch.
    """
    if not session.has_confirmed_record:
        return None

    record = session.uploaded_record
    reconciliation = record.reconciliation

    return ConfirmedRecordInputs(
        # Rounded because the engine takes whole hours. Both figures are whole
        # in every audit seen so far; rounding rather than truncating means a
        # hypothetical 80.5 doesn't quietly lose half an hour.
        credits_completed=round(record.completed_hours),
        credits_in_progress=round(record.in_progress_hours),
        credits_source=SOURCE_LABEL,
        credits_source_date=record.audit_prepared_at or "Not stated",
        catalog_year=record.catalog_year,
        program=record.program,
        totals_confirmed=bool(reconciliation and reconciliation.reconciled),
        unavailable=[_transferable_unavailable(prospective_label)],
    )
    