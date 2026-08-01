"""
Tests for the institution data loader.

The legacy change_major_reference.json equivalence test that used to live
here was retired in Stage 3, once real UNT data genuinely diverged from
that placeholder file's shape (different major keys, a restructured
tuition model) rather than just having different numbers in the same
shape. Structural/provenance correctness is now covered by the tests
below instead.
"""

import json
import os

import pytest

from ..loader import (
    MalformedInstitutionData,
    UnknownInstitution,
    build_reference_data,
    list_institutions,
    load_institution_file,
)


def test_registry_lists_unt():
    ids = [e["id"] for e in list_institutions()]
    assert "unt" in ids


def test_registry_files_exist_and_load():
    """Every registry entry must point at a file that exists and parses.
    Catches the 'renamed the file, forgot the index' mistake."""
    for entry in list_institutions():
        raw = load_institution_file(entry["id"])
        assert raw["institution_id"] == entry["id"]


def test_unknown_institution_raises_with_known_ids_listed():
    with pytest.raises(UnknownInstitution) as exc:
        build_reference_data("hogwarts")
    assert "unt" in str(exc.value)


def test_output_shape_matches_engine_contract():
    data = build_reference_data("unt")
    assert set(data.keys()) == {"institution", "majors", "credits_per_semester_full_time"}
    inst = data["institution"]
    assert "name" in inst
    assert "tuition" in inst
    for key in (
        "full_time_semester_estimate",
        "full_time_semester_estimate_source",
        "full_time_semester_estimate_source_date",
        "full_time_credit_threshold",
    ):
        assert key in inst["tuition"]


def test_final_supported_program_set_and_credit_hours():
    """Locks in the exact six programs Stage 3 verified, and their exact
    credit-hour totals, so a future data edit can't silently drop or
    mis-total a program without a test noticing."""
    data = build_reference_data("unt")
    expected = {
        "computer_science": 120,
        "information_technology": 121,
        "business_administration": 120,
        "psychology_ba": 120,
        "psychology_bs": 120,
        "mechanical_energy_engineering": 127,
    }
    assert set(data["majors"].keys()) == set(expected.keys())
    for key, hours in expected.items():
        assert data["majors"][key]["credits_required"] == hours, key
    # These three keys must NOT appear as real majors — they're handled by
    # major_resolution.py before reaching this data (alias, ambiguous, and
    # unsupported respectively), not as entries here.
    for retired_key in ("mechanical_engineering", "psychology", "nursing"):
        assert retired_key not in data["majors"]


def test_every_major_has_full_provenance():
    """A value without a source can't be cited, so it can't ship."""
    data = build_reference_data("unt")
    for key, major in data["majors"].items():
        for f in (
            "official_program_name",
            "degree_type",
            "credits_required_source",
            "credits_required_source_date",
        ):
            assert major.get(f), f"major '{key}' has empty '{f}'"

        # Earnings arrive from the Scorecard join, not the institution
        # file, and every major must end up with a block — even if its
        # figures are suppressed.
        earnings = major.get("earnings")
        assert earnings, f"major '{key}' has no earnings block"
        for period in ("1yr", "4yr", "5yr"):
            cell = earnings[period]
            assert cell["status"] in (
                "available",
                "privacy_suppressed",
                "unavailable",
            ), (key, period, cell["status"])
            # A missing figure must be None, never 0 — a zero would be an
            # invented fact dressed up as data.
            if cell["status"] != "available":
                assert cell["value"] is None, (key, period)


def test_missing_provenance_field_is_rejected(tmp_path, monkeypatch):
    """Hand-edit simulation: drop a salary_source and the loader must refuse
    to serve the file rather than pass an uncitable number to the engine."""
    from .. import loader

    good = load_institution_file("unt")
    del good["majors"]["computer_science"]["credits_required_source"]

    inst_dir = tmp_path / "institutions"
    inst_dir.mkdir()
    (inst_dir / "index.json").write_text(
        json.dumps({"institutions": [{"id": "unt", "display_name": "UNT",
                                      "file": "unt.json", "status": "placeholder_data"}]})
    )
    (inst_dir / "unt.json").write_text(json.dumps(good))

    monkeypatch.setattr(loader, "_INSTITUTIONS_DIR", str(inst_dir))
    monkeypatch.setattr(loader, "_INDEX_PATH", str(inst_dir / "index.json"))

    with pytest.raises(MalformedInstitutionData) as exc:
        build_reference_data("unt")
    assert "credits_required_source" in str(exc.value)
    assert "computer_science" in str(exc.value)


def test_engine_runs_on_loader_output():
    """End of the chain: the engine actually calculates from loader output.
    Shape tests above say it should work; this proves it does."""
    from decision_paths.change_major.engine import calculate
    from decision_paths.change_major.inputs import ChangeMajorInputs

    inputs = ChangeMajorInputs(
        current_major="computer_science",
        prospective_major="information_technology",
        credits_completed=72,
        credits_transferable=60,
    )
    result = calculate(inputs, build_reference_data("unt"))
    # Real 2025-2026 UNT data: CS requires 120 (48 remaining), IT requires
    # 121 (61 remaining). Tuition uses the verified $6,046/full-time-
    # semester estimate — see unt.json for the source. This value is
    # recomputed by the engine itself, not hand-derived, since the tuition
    # model's semester/threshold logic isn't simple multiplication.
    assert result.incremental_tuition.value == 5239.87
