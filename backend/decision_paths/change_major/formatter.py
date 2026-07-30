"""
Converts an engine ChangeMajorResult into the structured JSON object the
API returns and the frontend renders. This is the ONLY place that decides
what shape the result takes on the wire — the engine stays UI-agnostic,
the frontend stays calculation-agnostic.

The output shape here IS the "Why am I seeing this?" panel: every field in
`line_items` already carries source + source_date because the engine
attached it. The formatter does not add or remove provenance, only shapes it.
"""

from .tests.engine import ChangeMajorResult


def format_result(result: ChangeMajorResult) -> dict:
    def line_item(li):
        return {
            "label": li.label,
            "value": li.value,
            "source": li.source,
            "source_date": li.source_date,
        }

    return {
        "summary": {
            "current_major": result.current_major_display,
            "prospective_major": result.prospective_major_display,
            "credits_lost": result.credits_lost,
            "additional_semesters": result.additional_semesters,
            "total_cost_of_switching": result.total_cost_of_switching.value,
            "annual_salary_delta": result.annual_salary_delta.value,
        },
        "line_items": [
            line_item(result.additional_tuition_cost),
            line_item(result.foregone_earnings_cost),
            line_item(result.total_cost_of_switching),
            line_item(result.current_major_median_salary),
            line_item(result.prospective_major_median_salary),
            line_item(result.annual_salary_delta),
        ],
        "why_am_i_seeing_this": {
            "assumptions": result.assumptions,
            "limitations": result.limitations,
        },
    }