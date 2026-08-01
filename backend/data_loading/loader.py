"""
Loads institution data files and assembles them into the dict shape the
Change Major engine expects.

Why this module exists: the engine is pure math over a dict, and I want to
keep it that way. Everything institution-specific — which file to read,
how Scorecard and BLS data get joined in later — happens here instead. The
engine never learns that UNT exists.

Two rules for this file:
  1. No guessing. An unknown institution or a missing field raises with a
     specific message. It never falls back to a default number.
  2. Files are re-read on every call, same as the old _load_reference_data
     in main.py — the files are small and it means a value can be corrected
     mid-demo without a server restart. Cache later if it ever matters.
"""

import json
import os

_DATA_ROOT = os.path.join(os.path.dirname(__file__), "..", "data_sources")
_INSTITUTIONS_DIR = os.path.join(_DATA_ROOT, "institutions")
_INDEX_PATH = os.path.join(_INSTITUTIONS_DIR, "index.json")


class UnknownInstitution(ValueError):
    """Raised when an institution_id isn't in the registry. The API layer
    turns this into a 404 rather than a stack trace."""


class MalformedInstitutionData(ValueError):
    """Raised when an institution file exists but is missing something the
    engine needs. Naming the field beats a KeyError three layers down."""


# Fields every major entry must carry. Provenance fields are required on
# purpose — a number without a source can't render in the "Why am I seeing
# this?" panel, so it's malformed data, not a value with an empty citation.
# official_program_name and degree_type are required for real institution
# files (not the engine's own test fixtures) so a major key always traces
# back to an exact, named UNT program rather than an internal label.
_REQUIRED_MAJOR_FIELDS = (
    "display_name",
    "official_program_name",
    "degree_type",
    "credits_required",
    "credits_required_source",
    "credits_required_source_date",
)

_REQUIRED_TUITION_FIELDS = (
    "full_time_semester_estimate",
    "full_time_semester_estimate_source",
    "full_time_semester_estimate_source_date",
    "full_time_credit_threshold",
)


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_institutions() -> list[dict]:
    """Registry entries for every supported institution, including their
    data status ('placeholder_data' vs 'verified'). The frontend can use
    this for an institution picker later; for now it feeds validation."""
    index = _read_json(_INDEX_PATH)
    return index["institutions"]


def load_institution_file(institution_id: str) -> dict:
    """Raw institution file for one id, exactly as it sits on disk."""
    for entry in list_institutions():
        if entry["id"] == institution_id:
            path = os.path.join(_INSTITUTIONS_DIR, entry["file"])
            if not os.path.exists(path):
                raise MalformedInstitutionData(
                    f"Registry lists '{institution_id}' -> '{entry['file']}' "
                    "but that file doesn't exist."
                )
            return _read_json(path)
    known = ", ".join(e["id"] for e in list_institutions())
    raise UnknownInstitution(
        f"Unknown institution_id '{institution_id}'. Known: {known}."
    )


def _validate(raw: dict, institution_id: str) -> None:
    """Fail loudly on missing structure. This runs on every load rather than
    only in tests, so a hand-edited data file can't quietly ship a value
    with no citation attached."""
    if "tuition" not in raw:
        raise MalformedInstitutionData(f"'{institution_id}': missing 'tuition' block.")
    for f in _REQUIRED_TUITION_FIELDS:
        if f not in raw["tuition"]:
            raise MalformedInstitutionData(
                f"'{institution_id}': tuition block missing '{f}'."
            )

    if "credits_per_semester_full_time" not in raw:
        raise MalformedInstitutionData(
            f"'{institution_id}': missing 'credits_per_semester_full_time'."
        )

    majors = raw.get("majors")
    if not majors:
        raise MalformedInstitutionData(f"'{institution_id}': no 'majors' table.")
    for key, major in majors.items():
        for f in _REQUIRED_MAJOR_FIELDS:
            if f not in major or major[f] in ("", None):
                raise MalformedInstitutionData(
                    f"'{institution_id}': major '{key}' missing or empty '{f}'."
                )


_SCORECARD_DIR = os.path.join(_DATA_ROOT, "college_scorecard")


class MissingEarningsData(ValueError):
    """Raised when a major has no earnings entry at all. Distinct from a
    major whose earnings are present-but-suppressed: that's a real, honest
    answer from the federal data and flows through to the UI. This is a
    wiring mistake — someone added a major and forgot to map it."""


def _load_scorecard(institution_id: str) -> dict | None:
    """Processed College Scorecard earnings for one institution, or None if
    that institution has no Scorecard file yet. Absent is allowed — a new
    school can be added with academic data before earnings are wired up,
    and majors then carry an explicit 'unavailable' rather than blocking
    the whole request."""
    path = os.path.join(_SCORECARD_DIR, f"{institution_id}_field_of_study.json")
    if not os.path.exists(path):
        return None
    return _read_json(path)


def _attach_earnings(majors: dict, scorecard: dict | None, institution_id: str) -> None:
    """
    Folds Scorecard earnings into each major, in place.

    Every major ends up with an `earnings` block no matter what, so the
    engine and formatter never have to branch on presence. What varies is
    the per-metric `status`: 'available' carries a number, while
    'privacy_suppressed' and 'unavailable' carry None and a reason. Those
    two are kept apart deliberately — "too few graduates to publish" and
    "we have no data" are different facts and a student deserves to be
    told which one applies.
    """
    if scorecard is None:
        for major in majors.values():
            major["earnings"] = _absent_earnings(
                "No College Scorecard data has been imported for this "
                "institution yet."
            )
        return

    field_map = scorecard["fields_of_study"]
    major_map = scorecard["majors"]

    for key, major in majors.items():
        mapping = major_map.get(key)
        if mapping is None:
            raise MissingEarningsData(
                f"'{institution_id}': major '{key}' has no entry in "
                f"{institution_id}_field_of_study.json. Add it to MAJOR_MAP "
                "in scripts/import_scorecard.py and re-run the import, or "
                "the major will silently show no earnings."
            )

        cip_key = mapping["cip_4_digit"].replace(".", "")
        field = field_map.get(cip_key)
        if field is None:
            raise MissingEarningsData(
                f"'{institution_id}': major '{key}' maps to CIP "
                f"{mapping['cip_4_digit']}, which isn't in the processed "
                "Scorecard file."
            )

        major["earnings"] = {
            **{k: dict(v) for k, v in field["earnings"].items()},
            "cip_4_digit": field["cip_4_digit"],
            "cip_title": field["cip_title"],
            "degrees_awarded_in_field": field["degrees_awarded_in_field"],
            "shared_note": mapping.get("shared_note"),
            "source": scorecard["source"],
            "source_url": scorecard.get("source_url"),
            "dataset_release": scorecard["dataset_release"],
            "retrieved": scorecard["retrieved"],
            "credential_level_label": scorecard["credential_level_label"],
            "population_note": scorecard["population_note"],
        }


def _absent_earnings(reason: str) -> dict:
    """An earnings block for a major with no Scorecard coverage at all.
    Same shape as a real one so nothing downstream needs a special case.

    Built as one literal rather than a comprehension plus .update(): the
    block deliberately mixes nested dicts (the three periods) with plain
    scalars (the metadata), and splitting construction across two steps
    makes type checkers infer a narrower value type from the first half
    that the second half then violates.
    """

    def cell(label: str) -> dict:
        return {
            "value": None,
            "status": "unavailable",
            "status_note": reason,
            "label": label,
            "metric_code": None,
            "graduates_measured": None,
        }

    return {
        "1yr": cell("Median earnings 1 year after graduation"),
        "4yr": cell("Median earnings 4 years after graduation"),
        "5yr": cell("Median earnings 5 years after graduation"),
        "cip_4_digit": None,
        "cip_title": None,
        "degrees_awarded_in_field": None,
        "shared_note": None,
        "source": None,
        "source_url": None,
        "dataset_release": None,
        "retrieved": None,
        "credential_level_label": None,
        "population_note": None,
    }


_BLS_DIR = os.path.join(_DATA_ROOT, "bls")


def _load_bls_occupations(institution_id: str) -> dict | None:
    """Processed CIP-SOC-occupation data for one institution, or None if
    it hasn't been imported yet. Same 'absent is allowed' rule as
    Scorecard — a school can have academic and earnings data before its
    occupations file exists."""
    path = os.path.join(_BLS_DIR, f"{institution_id}_occupations.json")
    if not os.path.exists(path):
        return None
    return _read_json(path)


def _attach_occupations(majors: dict, bls: dict | None) -> None:
    """
    Folds BLS occupation data into each major, in place. Purely additive
    display context — nothing here is read by the calculation engine, so a
    missing or malformed occupations file degrades to an empty list rather
    than blocking a Change Major calculation that has nothing to do with
    career browsing.

    Unlike earnings, there's no MissingEarningsData-style hard failure for
    an unmapped major: occupations are optional context, and a major with
    none is a legitimate (if less useful) state, not a data bug.
    """
    for major in majors.values():
        major["occupations"] = _empty_occupations()

    if bls is None:
        return

    for key, major in majors.items():
        entry = bls["majors"].get(key)
        if entry is None:
            continue
        major["occupations"] = {
            "list": entry["occupations"],
            "crosswalk_source": bls["crosswalk_source"],
            "crosswalk_source_url": bls.get("crosswalk_source_url"),
            "crosswalk_limitation": bls["crosswalk_limitation"],
            "wage_source": bls["wage_source"],
            "wage_release": bls["wage_release"],
            "projections_source": bls["projections_source"],
            "projections_cycle": bls["projections_cycle"],
            "retrieved": bls["retrieved"],
        }


def _empty_occupations() -> dict:
    return {
        "list": [],
        "crosswalk_source": None,
        "crosswalk_source_url": None,
        "crosswalk_limitation": None,
        "wage_source": None,
        "wage_release": None,
        "projections_source": None,
        "projections_cycle": None,
        "retrieved": None,
    }


def build_reference_data(institution_id: str) -> dict:
    """
    The one function main.py calls. Returns the exact shape the engine
    already consumes:

        {
          "institution": {name, tuition: {...}},
          "majors": {...},
          "credits_per_semester_full_time": N,
        }

    Later stages join Scorecard and BLS data in here. The engine's contract
    doesn't change; this function's output just gets richer.
    """
    raw = load_institution_file(institution_id)
    _validate(raw, institution_id)

    majors = raw["majors"]
    _attach_earnings(majors, _load_scorecard(institution_id), institution_id)
    _attach_occupations(majors, _load_bls_occupations(institution_id))

    return {
        "institution": {
            "name": raw["display_name"],
            "tuition": raw["tuition"],
        },
        "majors": majors,
        "credits_per_semester_full_time": raw["credits_per_semester_full_time"],
    }
