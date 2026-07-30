"""
Deterministic calculation engine for the Change Major Decision Path.

Rules this file must never break:
  1. No network calls. No randomness. No calls to an AI model.
  2. Same inputs + same reference data snapshot -> always the same output.
  3. Every number in the output carries a `source` string, traceable back
     to the reference data file it came from.

If a future change to this file requires any of the above to bend, that
change belongs in a different module, not here.
"""

from dataclasses import dataclass, field

from .inputs import ChangeMajorInputs


@dataclass
class LineItem:
    """A single number in the result, with its provenance attached."""
    label: str
    value: float
    source: str
    source_date: str


@dataclass
class ChangeMajorResult:
    current_major_display: str
    prospective_major_display: str

    credits_lost: int
    additional_semesters: float
    additional_tuition_cost: LineItem
    foregone_earnings_cost: LineItem
    total_cost_of_switching: LineItem

    current_major_median_salary: LineItem
    prospective_major_median_salary: LineItem
    annual_salary_delta: LineItem

    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def calculate(inputs: ChangeMajorInputs, reference_data: dict) -> ChangeMajorResult:
    """
    Pure function: validated inputs + a reference data snapshot -> result.

    Raises ValueError for domain errors (e.g. unknown major key) rather than
    silently guessing — an engine that guesses is exactly what this
    architecture exists to prevent.
    """
    majors = reference_data["majors"]
    institution = reference_data["institution"]

    if inputs.current_major not in majors:
        raise ValueError(f"Unknown current_major key: '{inputs.current_major}'")
    if inputs.prospective_major not in majors:
        raise ValueError(f"Unknown prospective_major key: '{inputs.prospective_major}'")
    if inputs.current_major == inputs.prospective_major:
        raise ValueError("current_major and prospective_major must differ.")

    current = majors[inputs.current_major]
    prospective = majors[inputs.prospective_major]

    tuition_per_credit = institution["tuition_per_credit_hour"]
    credits_per_semester = reference_data["credits_per_semester_full_time"]

    # --- Core math ---------------------------------------------------

    credits_lost = inputs.credits_completed - inputs.credits_transferable

    # Credits still needed under the prospective major after transfer credit.
    credits_remaining_prospective = max(
        prospective["credits_required"] - inputs.credits_transferable, 0
    )
    additional_semesters = credits_remaining_prospective / credits_per_semester

    additional_tuition_cost = credits_remaining_prospective * tuition_per_credit

    # Foregone earnings: extra semesters spent in school instead of earning
    # the prospective major's median starting salary.
    foregone_earnings_cost = (additional_semesters / 2) * prospective["median_starting_salary"]

    total_cost_of_switching = additional_tuition_cost + foregone_earnings_cost

    annual_salary_delta = prospective["median_starting_salary"] - current["median_starting_salary"]

    # --- Assemble result with provenance on every line item ----------

    return ChangeMajorResult(
        current_major_display=current["display_name"],
        prospective_major_display=prospective["display_name"],
        credits_lost=credits_lost,
        additional_semesters=round(additional_semesters, 2),
        additional_tuition_cost=LineItem(
            label="Additional tuition to complete prospective major",
            value=round(additional_tuition_cost, 2),
            source=institution["source"],
            source_date=institution["source_date"],
        ),
        foregone_earnings_cost=LineItem(
            label="Foregone earnings during additional semesters",
            value=round(foregone_earnings_cost, 2),
            source=prospective["source"],
            source_date=prospective["source_date"],
        ),
        total_cost_of_switching=LineItem(
            label="Total estimated cost of switching",
            value=round(total_cost_of_switching, 2),
            source="Sum of additional tuition + foregone earnings (see line items above)",
            source_date="Calculated",
        ),
        current_major_median_salary=LineItem(
            label=f"Median starting salary — {current['display_name']}",
            value=current["median_starting_salary"],
            source=current["source"],
            source_date=current["source_date"],
        ),
        prospective_major_median_salary=LineItem(
            label=f"Median starting salary — {prospective['display_name']}",
            value=prospective["median_starting_salary"],
            source=prospective["source"],
            source_date=prospective["source_date"],
        ),
        annual_salary_delta=LineItem(
            label="Annual starting salary difference",
            value=annual_salary_delta,
            source="Calculated from the two median salary figures above",
            source_date="Calculated",
        ),
        assumptions=[
            "Foregone earnings are calculated using the prospective major's "
            "median STARTING salary, not lifetime earnings.",
            "Credits transferable is student-reported in v1, not verified "
            "against a degree audit system.",
            f"Assumes full-time enrollment at {credits_per_semester} credits/semester.",
            "Does not include scholarships, financial aid, or loan interest.",
        ],
        limitations=[
            "This is a projection based on median outcomes, not a prediction "
            "of this specific student's future earnings.",
            "Does not account for regional cost-of-living differences in "
            "post-graduation salary.",
            "Reference salary and tuition data may not reflect current-year figures — "
            "check source_date on each line item.",
        ],
    )