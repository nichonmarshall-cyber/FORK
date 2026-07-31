"""
Tests for the institution data loader.

The most important one here is the equivalence test: Stage 1 is supposed to
change WHERE data lives, not WHAT the engine sees. So the loader's output
for 'unt' must match the legacy change_major_reference.json exactly. Once
that legacy file is deleted (after real data lands), that test goes with it
and the remaining tests carry the weight.
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

_LEGACY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data_sources", "change_major_reference.json"
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
    for key in ("name", "tuition_per_credit_hour", "source", "source_date"):
        assert key in inst


def test_every_major_has_full_provenance():
    """A value without a source can't be cited, so it can't ship."""
    data = build_reference_data("unt")
    for key, major in data["majors"].items():
        for f in (
            "credits_required_source",
            "credits_required_source_date",
            "salary_source",
            "salary_source_date",
        ):
            assert major.get(f), f"major '{key}' has empty '{f}'"


def test_equivalent_to_legacy_reference_file():
    """Stage 1 must be a pure relocation: same numbers, same sources, same
    everything the engine reads. Compares against the legacy JSON, ignoring
    its _README and the institution name (legacy said REPLACE_WITH_YOUR_
    UNIVERSITY; the new file says the actual university)."""
    if not os.path.exists(_LEGACY_PATH):
        pytest.skip("legacy reference file already removed")

    with open(_LEGACY_PATH, encoding="utf-8") as f:
        legacy = json.load(f)

    new = build_reference_data("unt")

    # Compare every field the engine does math on. Source strings are
    # excluded deliberately: they're placeholder prose that was reworded in
    # the move and gets replaced with real citations in Stage 3. Presence
    # and non-emptiness of sources is covered by the provenance test above.
    assert set(new["majors"].keys()) == set(legacy["majors"].keys())
    for key in new["majors"]:
        for f in ("display_name", "credits_required", "median_starting_salary"):
            assert new["majors"][key][f] == legacy["majors"][key][f], (key, f)
    assert new["credits_per_semester_full_time"] == legacy["credits_per_semester_full_time"]
    assert (
        new["institution"]["tuition_per_credit_hour"]
        == legacy["institution"]["tuition_per_credit_hour"]
    )


def test_missing_provenance_field_is_rejected(tmp_path, monkeypatch):
    """Hand-edit simulation: drop a salary_source and the loader must refuse
    to serve the file rather than pass an uncitable number to the engine."""
    from .. import loader

    good = load_institution_file("unt")
    del good["majors"]["computer_science"]["salary_source"]

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
    assert "salary_source" in str(exc.value)
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
    # Same golden values as the engine's own regression test.
    assert result.incremental_tuition.value == 3600.0
