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
    "median_starting_salary",
    "salary_source",
    "salary_source_date",
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

    return {
        "institution": {
            "name": raw["display_name"],
            "tuition": raw["tuition"],
        },
        "majors": raw["majors"],
        "credits_per_semester_full_time": raw["credits_per_semester_full_time"],
    }
