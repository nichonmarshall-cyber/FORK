"""
Converts the raw College Scorecard "Field of Study" CSV into the small
processed file Fork actually reads at runtime.

Why this exists: the raw download is ~153 MB and 178 columns. Almost none
of that is relevant to us, and shipping it in the repo would be silly. This
script pulls the handful of rows and columns we need for one institution
and writes a file measured in kilobytes.

Raw data is NOT committed. Download it yourself from
https://collegescorecard.ed.gov/data (the "Most Recent Cohorts (Field of
Study)" zip), unzip it, and point this script at the CSV:

    python scripts/import_scorecard.py path/to/Most-Recent-Cohorts-Field-of-Study.csv

Two suppression markers in the source data mean different things and are
deliberately NOT collapsed into one:
  PS = privacy suppressed. The program exists and has graduates, but the
       cohort was too small to publish without risking re-identification.
  NA = not available. No data reported for this cell at all.
Neither ever becomes 0 — a missing earnings figure has to stay missing all
the way to the UI, or the whole provenance story is a lie.
"""

"""
Converts the raw College Scorecard "Field of Study" CSV into the small
processed file Fork actually reads at runtime.

Why this exists: the raw download is ~153 MB and 178 columns. Almost none
of that is relevant to us, and shipping it in the repo would be silly. This
script pulls the handful of rows and columns we need for one institution
and writes a file measured in kilobytes.

Raw data is NOT committed. Download it yourself from
https://collegescorecard.ed.gov/data (the "Most Recent Cohorts (Field of
Study)" zip), unzip it, and point this script at the CSV:

    python scripts/import_scorecard.py path/to/Most-Recent-Cohorts-Field-of-Study.csv

Two suppression markers in the source data mean different things and are
deliberately NOT collapsed into one:
  PS = privacy suppressed. The program exists and has graduates, but the
       cohort was too small to publish without risking re-identification.
  NA = not available. No data reported for this cell at all.
Neither ever becomes 0 — a missing earnings figure has to stay missing all
the way to the UI, or the whole provenance story is a lie.
"""

import csv
import json
import os
import sys
from datetime import date

UNITID = "227216"
INSTITUTION_ID = "unt"
CREDENTIAL_LEVEL = "3"  # bachelor's degree
CREDENTIAL_LABEL = "Bachelor's degree"

# Dataset release this script was written against. Printed into the output
# so a stale processed file is obvious rather than silently assumed current.
RELEASE = "2026-06-10"

SOURCE_NAME = (
    "U.S. Department of Education, College Scorecard — "
    "Most Recent Cohorts, Field of Study"
)
SOURCE_URL = "https://collegescorecard.ed.gov/data"

# Which 4-digit CIP codes we care about, and the human-readable earnings
# metrics we keep. Everything else in the 178-column file is dropped.
WANTED_CIPS = {
    "1101",  # Computer and Information Sciences, General
    "5202",  # Business Administration, Management and Operations
    "4201",  # Psychology, General
    "1419",  # Mechanical Engineering
}

EARNINGS_METRICS = [
    ("1yr", "EARN_MDN_1YR", "EARN_COUNT_WNE_1YR",
     "Median earnings 1 year after graduation"),
    ("4yr", "EARN_MDN_4YR", "EARN_COUNT_WNE_4YR",
     "Median earnings 4 years after graduation"),
    ("5yr", "EARN_MDN_5YR", "EARN_COUNT_WNE_5YR",
     "Median earnings 5 years after graduation"),
]

# Maps Fork's internal major keys onto CIP codes. Several majors share a
# code: the Scorecard only publishes at 4-digit CIP granularity, so it
# genuinely cannot separate them. Where that happens, `shared_note` is the
# student-facing sentence explaining what the number actually covers — it
# is not optional, and the loader refuses data that omits it.
MAJOR_MAP = {
    "computer_science": {
        "cip_4_digit": "1101",
        "shared_note": (
            "These earnings cover a broader group of related computing "
            "programs at UNT, not Computer Science on its own. UNT reports "
            "these programs to the federal government under a single "
            "category, so separate figures for each program don't exist."
        ),
    },
    "information_technology": {
        "cip_4_digit": "1101",
        "shared_note": (
            "These earnings cover a broader group of related computing "
            "programs at UNT, not Information Technology on its own. UNT "
            "reports these programs to the federal government under a "
            "single category, so separate figures for each program don't "
            "exist."
        ),
    },
    "business_administration": {
        "cip_4_digit": "5202",
        "shared_note": None,
    },
    "psychology_ba": {
        "cip_4_digit": "4201",
        "shared_note": (
            "These earnings include graduates of both psychology degree "
            "options at UNT, the B.A. and the B.S. The federal data groups "
            "them together, so separate figures for each degree don't exist."
        ),
    },
    "psychology_bs": {
        "cip_4_digit": "4201",
        "shared_note": (
            "These earnings include graduates of both psychology degree "
            "options at UNT, the B.A. and the B.S. The federal data groups "
            "them together, so separate figures for each degree don't exist."
        ),
    },
    "mechanical_energy_engineering": {
        "cip_4_digit": "1419",
        "shared_note": None,
    },
}

POPULATION_NOTE = (
    "These earnings only count students who received federal financial aid "
    "while studying, and who were working and not enrolled in school when "
    "their earnings were measured. Students who paid without federal aid, "
    "went straight to graduate school, or weren't working that year are not "
    "included."
)


def _parse_cell(raw: str) -> dict:
    """
    Turns one CSV cell into a value-with-status. The two suppression
    markers stay distinguishable, and a real number never gets confused
    with an absent one.
    """
    v = (raw or "").strip()
    if v == "PS":
        return {
            "value": None,
            "status": "privacy_suppressed",
            "status_note": (
                "Too few graduates to publish without risking identifying "
                "individual students."
            ),
        }
    if v in ("NA", ""):
        return {
            "value": None,
            "status": "unavailable",
            "status_note": "No figure reported for this program.",
        }
    try:
        return {"value": float(v), "status": "available", "status_note": None}
    except ValueError:
        # Unrecognized marker. Refuse to guess what it meant.
        return {
            "value": None,
            "status": "unavailable",
            "status_note": f"Unrecognized value in source data: {v!r}.",
        }


def _parse_count(raw: str):
    cell = _parse_cell(raw)
    return int(cell["value"]) if cell["status"] == "available" else None


def build(csv_path: str) -> dict:
    fields = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["UNITID"] != UNITID:
                continue
            if row["CREDLEV"] != CREDENTIAL_LEVEL:
                continue
            if row["CIPCODE"] not in WANTED_CIPS:
                continue

            earnings = {}
            for key, mdn_col, n_col, label in EARNINGS_METRICS:
                cell = _parse_cell(row[mdn_col])
                cell["label"] = label
                cell["metric_code"] = mdn_col
                cell["graduates_measured"] = _parse_count(row[n_col])
                earnings[key] = cell

            cip = row["CIPCODE"]
            fields[cip] = {
                "cip_4_digit": f"{cip[:2]}.{cip[2:]}",
                "cip_title": row["CIPDESC"].strip().rstrip("."),
                "degrees_awarded_in_field": _parse_count(row["IPEDSCOUNT2"]),
                "earnings": earnings,
            }

    missing = WANTED_CIPS - set(fields)
    if missing:
        raise SystemExit(
            f"Expected CIP codes not found for UNITID {UNITID}: {sorted(missing)}. "
            "Either the dataset changed or the wrong file was supplied."
        )

    majors = {}
    for major_key, cfg in MAJOR_MAP.items():
        cip = cfg["cip_4_digit"]
        majors[major_key] = {
            "cip_4_digit": f"{cip[:2]}.{cip[2:]}",
            "shared_note": cfg["shared_note"],
        }

    return {
        "_README": (
            "Processed subset of the College Scorecard Field of Study data "
            "for one institution. Generated by scripts/import_scorecard.py "
            "from the raw federal CSV, which is deliberately not committed "
            "to this repo. Do not hand-edit: re-run the script instead, so "
            "the numbers always trace back to a released federal dataset. "
            "A null earnings value is never a zero — check `status`."
        ),
        "institution_id": INSTITUTION_ID,
        "unitid": int(UNITID),
        "credential_level": int(CREDENTIAL_LEVEL),
        "credential_level_label": CREDENTIAL_LABEL,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "dataset_release": RELEASE,
        "retrieved": date.today().isoformat(),
        "population_note": POPULATION_NOTE,
        "fields_of_study": fields,
        "majors": majors,
    }


def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: python scripts/import_scorecard.py "
            "<Most-Recent-Cohorts-Field-of-Study.csv>"
        )
    csv_path = sys.argv[1]
    if not os.path.exists(csv_path):
        raise SystemExit(f"No such file: {csv_path}")

    data = build(csv_path)

    out_dir = os.path.join(
        os.path.dirname(__file__), "..", "data_sources", "college_scorecard"
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{INSTITUTION_ID}_field_of_study.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    print(f"Wrote {out_path}")
    for cip, field in sorted(data["fields_of_study"].items()):
        one = field["earnings"]["1yr"]
        shown = f"${one['value']:,.0f}" if one["value"] is not None else one["status"]
        print(f"  {field['cip_4_digit']}  {field['cip_title'][:44]:<44} 1yr={shown}")


if __name__ == "__main__":
    main()