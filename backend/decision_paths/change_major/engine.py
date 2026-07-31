"""
Calculations for the Change Major decision path.

Three rules for this file:
  1. No network calls, no randomness, no AI.
  2. Same inputs plus same reference data always gives the same answer.
  3. Every number that comes out carries a source string saying where it
     came from.

Anything that needs one of those bent belongs in a different module.

On the model: this reports the DIFFERENCE between the two paths, not the
cost of the new degree. Staying in your current major still costs money to
finish, so charging the full price of the new degree overstates switching
by a wide margin. Every figure here is (finish new major) minus (finish
current major).

That means results can be negative, which is a valid answer rather than a
bug — a shorter target degree makes switching cheaper and faster. Negatives
are reported as-is, not clamped to zero.
"""

from dataclasses import dataclass, field

from .inputs import ChangeMajorInputs


@dataclass
class LineItem:
    """A value and its provenance. One never travels without the other."""
    label: str
    value: float
    source: str
    source_date: str


@dataclass
class PathProjection:
    """One path priced out, either staying or switching. Kept separate so
    the UI can show both side by side instead of a single opaque total."""
    major_display: str
    credits_required: LineItem
    credits_counted: LineItem
    credits_remaining: LineItem
    semesters_remaining: LineItem
    tuition_remaining: LineItem
    official_program_name: str | None = None
    degree_type: str | None = None


@dataclass
class ChangeMajorResult:
    current_path: PathProjection
    prospective_path: PathProjection

    credits_lost: LineItem
    incremental_semesters: LineItem
    incremental_tuition: LineItem
    foregone_earnings_cost: LineItem
    incremental_total_cost: LineItem

    current_major_median_salary: LineItem
    prospective_major_median_salary: LineItem
    annual_salary_delta: LineItem

    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def _project_tuition_cost(
    remaining_credits: float,
    full_time_semester_estimate: float,
    full_time_credit_threshold: float,
    standard_full_time_load: float,
) -> tuple[float, bool]:
    """
    Projects tuition by counting full-time SEMESTERS, not by multiplying
    remaining credits by a per-credit rate. UNT (like most Texas publics)
    bills a flat rate for any enrollment from the full-time threshold up to
    the standard full-time load, and an hourly rate below that threshold —
    so "every credit costs the same" is not how the real bill works, and a
    flat-rate-times-credits formula would overstate a light final semester
    and understate a heavy one.

    Whole full-time semesters (standard_full_time_load credits each) each
    cost full_time_semester_estimate. Any remainder is checked against the
    threshold:
      - remainder >= threshold: still flat-rate territory at UNT (12-15
        hours costs the same), so it's billed as one more full-time
        semester.
      - 0 < remainder < threshold: genuinely hourly billing, and this
        engine doesn't have a verified hourly rate. Rather than inventing
        one, this approximates that remainder proportionally from the
        full-time rate and flags it — the caller surfaces that flag as a
        limitation rather than presenting the whole total as verified.

    Returns (total_cost, final_semester_is_estimated).
    """
    if remaining_credits <= 0:
        return 0.0, False

    full_time_semesters = int(remaining_credits // standard_full_time_load)
    remainder = remaining_credits - (full_time_semesters * standard_full_time_load)

    final_semester_is_estimated = False
    if remainder > 0:
        if remainder >= full_time_credit_threshold:
            full_time_semesters += 1
            remainder = 0.0
        else:
            final_semester_is_estimated = True

    total = full_time_semesters * full_time_semester_estimate
    if final_semester_is_estimated:
        total += (remainder / standard_full_time_load) * full_time_semester_estimate

    return total, final_semester_is_estimated


def calculate(inputs: ChangeMajorInputs, reference_data: dict) -> ChangeMajorResult:
    """
    Validated inputs plus reference data in, result out. No side effects.

    Raises on an unknown major rather than guessing the closest match. An
    engine that guesses is the failure mode this design exists to prevent.
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

    tuition_model = institution["tuition"]
    full_time_semester_estimate = tuition_model["full_time_semester_estimate"]
    full_time_credit_threshold = tuition_model["full_time_credit_threshold"]
    tuition_source = tuition_model["full_time_semester_estimate_source"]
    tuition_date = tuition_model["full_time_semester_estimate_source_date"]
    tuition_below_full_time_note = tuition_model.get("below_full_time_note")
    credits_per_semester = reference_data["credits_per_semester_full_time"]

    # --- Credits required: prefer an audit over the reference table -----
    # A degree audit from the registrar is more reliable than the
    # hand-entered JSON table, so it takes precedence when supplied. It
    # brings its own source string so the citation stays accurate.
    if inputs.prospective_credits_required is not None:
        prospective_required = float(inputs.prospective_credits_required)
        prospective_required_source = (
            inputs.prospective_credits_required_source
            or "Student-supplied degree audit"
        )
        # The date that applies to an override is when THAT figure was
        # obtained, not whenever the reference table happens to have been
        # last updated. inputs.credits_source_date is the date attached to
        # the audit/credits data the student supplied, so it's the correct
        # date for this line item too. Bug: this used to always cite
        # prospective["credits_required_source_date"] even when the source
        # string above came from the override — a mismatched citation.
        prospective_required_source_date = inputs.credits_source_date
    else:
        prospective_required = float(prospective["credits_required"])
        prospective_required_source = prospective["credits_required_source"]
        prospective_required_source_date = prospective["credits_required_source_date"]

    current_required = float(current["credits_required"])

    # --- Core math ------------------------------------------------------

    # Completed credits that count toward nothing in the new degree.
    #
    # Not the same as "credits outside the new major." Coursework that
    # doesn't satisfy a major requirement usually still counts as elective
    # hours toward the degree, and switching within a field (CS -> IT, say)
    # often carries most credits over intact. So this figure is only the
    # portion that applies nowhere, which is typically small and can be
    # zero. Whether a credit applies is the registrar's call, not ours —
    # see credits_transferable in inputs.py.
    credits_lost = inputs.credits_completed - inputs.credits_transferable

    # What each path still costs from this point forward.
    credits_remaining_current = max(current_required - inputs.credits_completed, 0.0)
    credits_remaining_prospective = max(prospective_required - inputs.credits_transferable, 0.0)

    semesters_remaining_current = credits_remaining_current / credits_per_semester
    semesters_remaining_prospective = credits_remaining_prospective / credits_per_semester

    tuition_remaining_current, current_final_semester_estimated = _project_tuition_cost(
        credits_remaining_current,
        full_time_semester_estimate,
        full_time_credit_threshold,
        credits_per_semester,
    )
    tuition_remaining_prospective, prospective_final_semester_estimated = _project_tuition_cost(
        credits_remaining_prospective,
        full_time_semester_estimate,
        full_time_credit_threshold,
        credits_per_semester,
    )
    any_final_semester_estimated = (
        current_final_semester_estimated or prospective_final_semester_estimated
    )

    # The gap between the two paths. This is the figure that matters.
    incremental_semesters = semesters_remaining_prospective - semesters_remaining_current
    incremental_tuition = tuition_remaining_prospective - tuition_remaining_current

    # Delayed earnings apply only to the additional time, valued at what
    # the new major pays. Two semesters to a year.
    foregone_earnings_cost = (incremental_semesters / 2) * prospective["median_starting_salary"]

    incremental_total_cost = incremental_tuition + foregone_earnings_cost

    annual_salary_delta = (
        prospective["median_starting_salary"] - current["median_starting_salary"]
    )

    # --- Build the result, with a source on every value -----------------

    current_path = PathProjection(
        major_display=current["display_name"],
        official_program_name=current.get("official_program_name"),
        degree_type=current.get("degree_type"),
        credits_required=LineItem(
            label=f"Credits required — {current['display_name']}",
            value=current_required,
            source=current["credits_required_source"],
            source_date=current["credits_required_source_date"],
        ),
        credits_counted=LineItem(
            label="Credits already completed",
            value=float(inputs.credits_completed),
            source=inputs.credits_source,
            source_date=inputs.credits_source_date,
        ),
        credits_remaining=LineItem(
            label="Credits still needed to finish current major",
            value=credits_remaining_current,
            source="Credits required minus credits completed",
            source_date="Calculated",
        ),
        semesters_remaining=LineItem(
            label="Semesters still needed",
            value=round(semesters_remaining_current, 2),
            source=f"Credits remaining / {credits_per_semester} credits per semester",
            source_date="Calculated",
        ),
        tuition_remaining=LineItem(
            label="Tuition still to pay",
            value=round(tuition_remaining_current, 2),
            source=tuition_source,
            source_date=tuition_date,
        ),
    )

    prospective_path = PathProjection(
        major_display=prospective["display_name"],
        official_program_name=prospective.get("official_program_name"),
        degree_type=prospective.get("degree_type"),
        credits_required=LineItem(
            label=f"Credits required — {prospective['display_name']}",
            value=prospective_required,
            source=prospective_required_source,
            source_date=prospective_required_source_date,
        ),
        credits_counted=LineItem(
            label="Credits that transfer to prospective major",
            value=float(inputs.credits_transferable),
            source=inputs.credits_transferable_source,
            source_date=inputs.credits_source_date,
        ),
        credits_remaining=LineItem(
            label="Credits still needed to finish prospective major",
            value=credits_remaining_prospective,
            source="Credits required minus credits that transfer",
            source_date="Calculated",
        ),
        semesters_remaining=LineItem(
            label="Semesters still needed",
            value=round(semesters_remaining_prospective, 2),
            source=f"Credits remaining / {credits_per_semester} credits per semester",
            source_date="Calculated",
        ),
        tuition_remaining=LineItem(
            label="Tuition still to pay",
            value=round(tuition_remaining_prospective, 2),
            source=tuition_source,
            source_date=tuition_date,
        ),
    )

    return ChangeMajorResult(
        current_path=current_path,
        prospective_path=prospective_path,
        credits_lost=LineItem(
            label="Completed credits that count toward nothing in the new degree",
            value=float(credits_lost),
            source=f"{inputs.credits_source} minus {inputs.credits_transferable_source}",
            source_date=inputs.credits_source_date,
        ),
        incremental_semesters=LineItem(
            label="Additional semesters (negative means fewer)",
            value=round(incremental_semesters, 2),
            source="Semesters remaining on prospective path minus current path",
            source_date="Calculated",
        ),
        incremental_tuition=LineItem(
            label="Additional tuition (negative means less)",
            value=round(incremental_tuition, 2),
            source="Tuition remaining on prospective path minus current path",
            source_date="Calculated",
        ),
        foregone_earnings_cost=LineItem(
            label="Earnings delayed by the additional time",
            value=round(foregone_earnings_cost, 2),
            source=prospective["salary_source"],
            source_date=prospective["salary_source_date"],
        ),
        incremental_total_cost=LineItem(
            label="Estimated total difference from switching",
            value=round(incremental_total_cost, 2),
            source="Additional tuition + delayed earnings (see line items above)",
            source_date="Calculated",
        ),
        current_major_median_salary=LineItem(
            label=f"Median starting salary — {current['display_name']}",
            value=float(current["median_starting_salary"]),
            source=current["salary_source"],
            source_date=current["salary_source_date"],
        ),
        prospective_major_median_salary=LineItem(
            label=f"Median starting salary — {prospective['display_name']}",
            value=float(prospective["median_starting_salary"]),
            source=prospective["salary_source"],
            source_date=prospective["salary_source_date"],
        ),
        annual_salary_delta=LineItem(
            label="Annual starting salary difference",
            value=float(annual_salary_delta),
            source="Calculated from the two median salary figures above",
            source_date="Calculated",
        ),
        assumptions=[
            "Costs shown are the difference between finishing the new major "
            "and finishing your current one, not the full price of the new "
            "degree.",
            "Delayed earnings use the new major's median starting salary, "
            "not lifetime earnings.",
            f"Assumes full-time enrollment at {credits_per_semester} credits "
            "per semester on both paths.",
            f"Credits completed: {inputs.credits_source}. "
            f"Credits transferable: {inputs.credits_transferable_source}.",
            "Courses in progress are not counted as completed.",
            "Credits that don't satisfy a requirement in the new major may "
            "still count toward your degree as electives. Only credits that "
            "apply nowhere are treated as lost here.",
            "Does not include scholarships, financial aid, or loan interest.",
            "Tuition is projected by full-time SEMESTER, not by multiplying "
            "remaining credits by a flat per-credit rate — most Texas public "
            "universities, including UNT, bill a flat rate across a full-time "
            "band of hours rather than charging proportionally per credit.",
        ],
        limitations=_build_limitations(
            current,
            prospective,
            tuition_below_full_time_note=tuition_below_full_time_note,
            any_final_semester_estimated=any_final_semester_estimated,
        ),
    )


def _build_limitations(
    current: dict,
    prospective: dict,
    tuition_below_full_time_note: str | None,
    any_final_semester_estimated: bool,
) -> list[str]:
    """Assembled separately from the main return so the always-present
    limitations, the tuition-model caveat, and any major-specific notes
    (e.g. an umbrella BBA degree needing a declared professional field)
    don't get lost in one long inline list literal."""
    limitations = [
        "Based on median outcomes across a group of graduates. Not a "
        "prediction about any individual student.",
        "Not adjusted for cost of living where you end up working.",
        "Tuition is an estimate derived from a published full-time rate. "
        "Actual charges vary by tuition plan, residency, program "
        "differential tuition, course fees, campus location, and online "
        "vs. on-campus enrollment.",
        "Salary and tuition data may not be current. Check the date on "
        "each line item.",
    ]

    if any_final_semester_estimated and tuition_below_full_time_note:
        limitations.append(
            "At least one projected final semester in this plan falls "
            "below the full-time credit-hour threshold, where tuition is "
            "billed hourly rather than at the flat full-time rate. "
            f"{tuition_below_full_time_note}"
        )

    for major in (current, prospective):
        for note in major.get("program_limitations", []):
            if note not in limitations:
                limitations.append(f"{major['display_name']}: {note}")

    return limitations
