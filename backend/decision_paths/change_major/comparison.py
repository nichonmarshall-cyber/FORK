"""
Runs the pairwise Change Major engine once per alternative and assembles
the results into one comparison snapshot.

This is the layer that makes "compare me against three majors" a single
user action. It does no math. Every number in the snapshot came out of
engine.calculate(), which has no idea it's being called as part of
something larger — that's the whole point of building it this way instead
of rewriting the engine to take N majors.

Two things this file is responsible for beyond fanning out:

  1. Grouping each pairwise result into named dimension blocks
     (financial, timeline, credits, career). Regrouping only — no value is
     recomputed, rounded, or combined. The blocks exist so the scoped
     views layer can slice by topic without string-matching line item
     labels, which would break the moment someone rewords one.

  2. Partial results. An option missing its transferable-credit figure is
     marked pending and the rest still run. An option whose figures fail
     validation is marked failed with the reason. Neither case takes down
     the comparison, and neither one ever gets a guessed value.

Anchor-relative by design: every pairwise run is (current major -> one
alternative), so all the alternatives share a baseline and can be read
side by side. A true alternative-to-alternative run answers a different
question ("if I were already a CS student...") and is never started from
here.
"""

from dataclasses import dataclass, field

from pydantic import ValidationError

from .comparison_inputs import ComparisonOption, MultiComparisonInputs
from .engine import ChangeMajorResult
from .formatter import _line_item as _serialize_line_item

# Status values an option can carry in the snapshot. Kept as constants so
# the router, views, and endpoint can't drift on spelling.
STATUS_CALCULATED = "calculated"
STATUS_PENDING = "pending"
STATUS_FAILED = "failed"


@dataclass
class OptionOutcome:
    """
    One alternative's place in the comparison — calculated, pending, or
    failed. A pending option is still part of the comparison; it just has
    a question attached to it instead of numbers.
    """

    major_key: str
    major_display: str
    status: str
    dimensions: dict | None = None
    missing_fields: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        out = {
            "major_key": self.major_key,
            "major": self.major_display,
            "status": self.status,
        }
        if self.dimensions is not None:
            out["dimensions"] = self.dimensions
        if self.missing_fields:
            out["missing_fields"] = self.missing_fields
        if self.error:
            out["error"] = self.error
        return out


@dataclass
class MultiComparisonSnapshot:
    """
    The assembled result of one fan-out. This is the trusted factual
    object every explanation is grounded against — nothing the AI wrote
    ever gets folded back into it.
    """

    anchor_key: str
    anchor_display: str
    credits_completed: int
    outcomes: list[OptionOutcome]
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def calculated(self) -> list[OptionOutcome]:
        return [o for o in self.outcomes if o.status == STATUS_CALCULATED]

    def pending(self) -> list[OptionOutcome]:
        return [o for o in self.outcomes if o.status == STATUS_PENDING]

    def failed(self) -> list[OptionOutcome]:
        return [o for o in self.outcomes if o.status == STATUS_FAILED]

    def outcome_for(self, major_key: str) -> OptionOutcome | None:
        return next((o for o in self.outcomes if o.major_key == major_key), None)

    def to_dict(self) -> dict:
        return {
            "anchor": {"major_key": self.anchor_key, "major": self.anchor_display},
            "credits_completed": self.credits_completed,
            "options": [o.to_dict() for o in self.outcomes],
            "assumptions": self.assumptions,
            "limitations": self.limitations,
        }


def _dimensions_from_result(result: ChangeMajorResult) -> dict:
    """
    Regroups one pairwise result into the four topic blocks.

    A few values legitimately appear in more than one block. Additional
    semesters belongs to timeline, but it's also what drives the cost
    difference, so a financial answer that can't mention it is worse than
    one that can. Credits remaining shows up in both credits and timeline
    for the same reason. Duplication here is cheap; a scoped view missing
    the number that explains its own headline figure is not.
    """
    li = _serialize_line_item

    return {
        "financial": {
            "incremental_tuition": li(result.incremental_tuition),
            "foregone_earnings_cost": li(result.foregone_earnings_cost),
            "incremental_total_cost": li(result.incremental_total_cost),
            "tuition_remaining_current": li(result.current_path.tuition_remaining),
            "tuition_remaining_prospective": li(result.prospective_path.tuition_remaining),
            "incremental_semesters": li(result.incremental_semesters),
        },
        "timeline": {
            "incremental_semesters": li(result.incremental_semesters),
            "semesters_remaining_current": li(result.current_path.semesters_remaining),
            "semesters_remaining_prospective": li(result.prospective_path.semesters_remaining),
            "credits_remaining_current": li(result.current_path.credits_remaining),
            "credits_remaining_prospective": li(result.prospective_path.credits_remaining),
        },
        "credits": {
            "credits_lost": li(result.credits_lost),
            "credits_completed": li(result.current_path.credits_counted),
            "credits_transferable": li(result.prospective_path.credits_counted),
            "credits_required_current": li(result.current_path.credits_required),
            "credits_required_prospective": li(result.prospective_path.credits_required),
            "credits_remaining_prospective": li(result.prospective_path.credits_remaining),
        },
        "career": {
            "median_salary_current": li(result.current_major_median_salary),
            "median_salary_prospective": li(result.prospective_major_median_salary),
            "annual_salary_delta": li(result.annual_salary_delta),
            "earnings_context": result.earnings_context,
            "career_context": result.career_context,
        },
        "program": {
            "official_program_name": result.prospective_path.official_program_name,
            "degree_type": result.prospective_path.degree_type,
        },
    }


def _merge_unique(target: list[str], additions: list[str]) -> None:
    """Union preserving first-seen order. Every pairwise run repeats the
    same assumptions about tuition modelling and full-time enrollment, and
    a snapshot that states them four times reads like four different
    caveats."""
    for item in additions:
        if item not in target:
            target.append(item)


def run_multi_comparison(
    inputs: MultiComparisonInputs,
    reference_data: dict,
    calculate=None,
) -> MultiComparisonSnapshot:
    """
    Fan out across every alternative and assemble the snapshot.

    `calculate` is injectable purely so tests can run the assembly logic
    without the full reference dataset. Production always uses the real
    engine.

    Reference data is loaded ONCE by the caller and reused across every
    run, rather than re-read per pair. Three alternatives shouldn't mean
    three passes over the institution files.
    """
    if calculate is None:
        from .engine import calculate as engine_calculate

        calculate = engine_calculate

    majors = reference_data["majors"]
    if inputs.current_major not in majors:
        raise ValueError(f"Unknown current_major key: '{inputs.current_major}'")

    anchor_display = majors[inputs.current_major]["display_name"]

    outcomes: list[OptionOutcome] = []
    assumptions: list[str] = []
    limitations: list[str] = []

    for option in inputs.options:
        display = _display_name(option, majors)

        if not option.is_complete:
            outcomes.append(
                OptionOutcome(
                    major_key=option.major,
                    major_display=display,
                    status=STATUS_PENDING,
                    missing_fields=option.missing_fields(),
                )
            )
            continue

        if option.major not in majors:
            outcomes.append(
                OptionOutcome(
                    major_key=option.major,
                    major_display=display,
                    status=STATUS_FAILED,
                    error=f"'{option.major}' isn't a major this institution's data covers.",
                )
            )
            continue

        try:
            pairwise = inputs.to_pairwise_inputs(option)
        except ValidationError as e:
            # One option's bad figure marks that option failed. The other
            # three still run — losing a whole comparison because one
            # number was typed wrong would be a worse experience than
            # showing three results and one clear error.
            outcomes.append(
                OptionOutcome(
                    major_key=option.major,
                    major_display=display,
                    status=STATUS_FAILED,
                    error=_first_validation_message(e),
                )
            )
            continue

        try:
            result = calculate(pairwise, reference_data)
        except ValueError as e:
            outcomes.append(
                OptionOutcome(
                    major_key=option.major,
                    major_display=display,
                    status=STATUS_FAILED,
                    error=str(e),
                )
            )
            continue

        outcomes.append(
            OptionOutcome(
                major_key=option.major,
                major_display=result.prospective_path.major_display,
                status=STATUS_CALCULATED,
                dimensions=_dimensions_from_result(result),
            )
        )
        _merge_unique(assumptions, result.assumptions)
        _merge_unique(limitations, result.limitations)

    return MultiComparisonSnapshot(
        anchor_key=inputs.current_major,
        anchor_display=anchor_display,
        credits_completed=inputs.credits_completed,
        outcomes=outcomes,
        assumptions=assumptions,
        limitations=limitations,
    )


def _display_name(option: ComparisonOption, majors: dict) -> str:
    """Falls back to the raw key for a major the institution doesn't have,
    so the failure message can still name what the student asked for."""
    entry = majors.get(option.major)
    return entry["display_name"] if entry else option.major


def _first_validation_message(exc: ValidationError) -> str:
    """Pydantic's raw error text carries type codes and input reprs that
    mean nothing to a student. The validators in inputs.py already write
    plain-English messages, so use those."""
    errors = exc.errors()
    if not errors:
        return "This option's inputs didn't validate."
    original = errors[0].get("ctx", {}).get("error")
    message = str(original) if original is not None else errors[0]["msg"]
    return message.removeprefix("Value error, ")
