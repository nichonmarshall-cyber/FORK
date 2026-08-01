"""
Turns an engine result into the JSON the API returns.

The only place that decides the shape of a response. The engine doesn't
know a frontend exists, and the frontend doesn't know how the math works.
Change the UI, change this file, leave the engine alone.

The why_am_i_seeing_this key is the provenance panel, and it costs nothing
to build — the engine already attached a source to every value, so this
just passes it through. No calculation happens here.
"""

from .engine import ChangeMajorResult, LineItem, PathProjection


def _line_item(li: LineItem) -> dict:
    item = {
        "label": li.label,
        "value": li.value,
        "source": li.source,
        "source_date": li.source_date,
    }
    # Only emitted when something is actually off, so the common case stays
    # uncluttered. A null value with a status is the signal to the frontend
    # to render "not available" plus the reason — never a 0 or a dash.
    if li.status != "available":
        item["status"] = li.status
        item["status_note"] = li.status_note
    return item


def _path(p: PathProjection) -> dict:
    path_dict = {
        "major": p.major_display,
        "line_items": [
            _line_item(p.credits_required),
            _line_item(p.credits_counted),
            _line_item(p.credits_remaining),
            _line_item(p.semesters_remaining),
            _line_item(p.tuition_remaining),
        ],
    }
    # Only present when the reference data supplies them — older or
    # synthetic reference data (e.g. engine test fixtures) may not have
    # these, and the frontend shouldn't render a blank field for it.
    if p.official_program_name:
        path_dict["official_program_name"] = p.official_program_name
    if p.degree_type:
        path_dict["degree_type"] = p.degree_type
    return path_dict


def format_result(result: ChangeMajorResult) -> dict:
    return {
        # Headline figures. All of these are differences between the two
        # paths, and any of them can be negative. The frontend needs to
        # render a negative as a saving, not as an error state.
        "summary": {
            "current_major": result.current_path.major_display,
            "prospective_major": result.prospective_path.major_display,
            "credits_lost": result.credits_lost.value,
            "incremental_semesters": result.incremental_semesters.value,
            "incremental_tuition": result.incremental_tuition.value,
            "incremental_total_cost": result.incremental_total_cost.value,
            "annual_salary_delta": result.annual_salary_delta.value,
        },
        # Both paths priced separately, so the student can see the two
        # options rather than taking a single summary number on faith.
        "comparison": {
            "staying": _path(result.current_path),
            "switching": _path(result.prospective_path),
        },
        "line_items": [
            _line_item(result.credits_lost),
            _line_item(result.incremental_semesters),
            _line_item(result.incremental_tuition),
            _line_item(result.foregone_earnings_cost),
            _line_item(result.incremental_total_cost),
            _line_item(result.current_major_median_salary),
            _line_item(result.prospective_major_median_salary),
            _line_item(result.annual_salary_delta),
        ],
        # Career context: the 1/4/5-year earnings trajectory for each
        # program, what the federal category actually covers, and how many
        # degrees it represents. Display-only — none of this is multiplied
        # into any figure above.
        "earnings_context": result.earnings_context,
        "career_context": result.career_context,
        "why_am_i_seeing_this": {
            "assumptions": result.assumptions,
            "limitations": result.limitations,
        },
    }
