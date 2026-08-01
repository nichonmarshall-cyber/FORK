"""
Tests for the CIP-SOC-occupation join.

Two things matter here that don't show up in the Scorecard tests:
  1. The occupation list has to be sorted by an objective figure (national
     employment), not by any judgment call about which jobs are "best".
  2. The crosswalk's own limitation — expert-judgment relatedness, not
     outcomes data — has to stay a SEPARATE fact from the Scorecard's
     population limitation. They're weaknesses in two different datasets
     and collapsing them into one warning would blur that.
"""

import pytest

from decision_paths.change_major.engine import calculate
from decision_paths.change_major.inputs import ChangeMajorInputs

from ..loader import build_reference_data


@pytest.fixture
def reference_data():
    return build_reference_data("unt")


def test_every_major_has_occupations(reference_data):
    for key, major in reference_data["majors"].items():
        occs = major["occupations"]["list"]
        assert occs, f"major '{key}' has no occupations"


def test_occupations_sorted_by_national_employment_descending(reference_data):
    for key, major in reference_data["majors"].items():
        employments = [
            o["national_employment"]
            for o in major["occupations"]["list"]
            if o["national_employment"] is not None
        ]
        assert employments == sorted(employments, reverse=True), key


def test_cs_and_it_share_the_same_occupation_list(reference_data):
    """Same Scorecard category in Stage 4, same crosswalk match here —
    consistent with how the rest of the pipeline treats them as one field
    for anything the federal data can't separate."""
    cs = reference_data["majors"]["computer_science"]["occupations"]["list"]
    it = reference_data["majors"]["information_technology"]["occupations"]["list"]
    assert cs == it


def test_wage_and_growth_carry_distinct_sources_and_dates(reference_data):
    occs = reference_data["majors"]["mechanical_energy_engineering"]["occupations"]
    assert "OEWS" in occs["wage_source"]
    assert occs["wage_release"] == "May 2025"
    assert "Employment Projections" in occs["projections_source"]
    assert occs["projections_cycle"] == "2024-2034"
    # Genuinely different strings — the two facts must not be forced
    # through one shared date, since they come from different releases.
    assert occs["wage_release"] != occs["projections_cycle"]


def test_crosswalk_limitation_is_present_and_distinct_from_population_note(
    reference_data,
):
    result = calculate(
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="mechanical_energy_engineering",
            credits_completed=72,
            credits_transferable=60,
        ),
        reference_data,
    )
    crosswalk = [
        lim
        for lim in result.limitations
        if "expert judgment" in lim.lower() or "crosswalk" in lim.lower()
    ]
    population = [
        lim for lim in result.limitations if "federal financial aid" in lim.lower()
    ]
    assert crosswalk, "crosswalk limitation must be present"
    assert population, "Scorecard population limitation must still be present"
    assert crosswalk[0] != population[0]

    text = crosswalk[0].lower()
    assert "does not" in text or "not represent" in text
    assert "placement" in text


def test_career_context_never_appears_in_a_calculation():
    """career_context is display-only. Corrupting it must not change any
    number the engine actually computes."""
    ref = build_reference_data("unt")
    baseline = calculate(
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="mechanical_energy_engineering",
            credits_completed=72,
            credits_transferable=60,
        ),
        ref,
    )

    ref["majors"]["computer_science"]["occupations"]["list"] = [
        {
            "soc_code": "00-0000",
            "title": "Fake Occupation",
            "median_annual_wage": 999999.0,
            "national_employment": 1,
            "percent_change_2024_2034": 500.0,
            "annual_openings": 1.0,
            "typical_education": "None",
        }
    ]
    mutated = calculate(
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="mechanical_energy_engineering",
            credits_completed=72,
            credits_transferable=60,
        ),
        ref,
    )

    assert mutated.incremental_tuition.value == baseline.incremental_tuition.value
    assert mutated.foregone_earnings_cost.value == baseline.foregone_earnings_cost.value
    assert (
        mutated.incremental_total_cost.value == baseline.incremental_total_cost.value
    )


def test_missing_occupations_file_degrades_to_empty_not_a_crash():
    """An institution with no BLS import yet must still calculate — career
    context is optional, unlike credits or tuition."""
    from .. import loader

    ref = build_reference_data("unt")
    for major in ref["majors"].values():
        major["occupations"] = None  # simulate a major with nothing attached

    result = calculate(
        ChangeMajorInputs(
            current_major="computer_science",
            prospective_major="mechanical_energy_engineering",
            credits_completed=72,
            credits_transferable=60,
        ),
        ref,
    )
    assert result.career_context[0]["occupations"] == []
    assert result.incremental_tuition.value is not None
