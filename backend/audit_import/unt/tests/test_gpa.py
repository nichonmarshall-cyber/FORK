"""GPA as a UNT degree audit states it."""

from pathlib import Path

import pytest

from audit_import.unt.gpa import parse_gpa
from audit_import.unt.parser import parse_audit_text

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.mark.parametrize(
    "name,gpa,hours,points",
    [("unt_audit_standard.txt", 2.919, 87.0, 254.0), ("unt_audit_whatif.txt", 3.030, 66.0, 200.0)],
)
def test_real_exports_reconcile(name, gpa, hours, points):
    record = parse_audit_text((FIXTURES / name).read_text(encoding="utf-8"))
    assert record.gpa.cumulative_gpa == gpa
    assert record.gpa.attempted_hours == hours
    assert record.gpa.quality_points == points
    assert record.gpa.reconciled is True


def test_unt_truncates_rather_than_rounds():
    """254/87 = 2.9195 prints as 2.919. A rounding check would call the
    audit wrong; a truncation check accepts it and rejects 2.920."""
    lines = ["UGRD UNT Cumulative GPA: 2.919", "-- GPA (ALL COURSES)", "87.0ATTEMPTED HOURS 254.0POINTS 2.919AVG"]
    assert parse_gpa(lines).reconciled is True
    bad = ["UGRD UNT Cumulative GPA: 2.920", "-- GPA (ALL COURSES)", "87.0ATTEMPTED HOURS 254.0POINTS 2.920AVG"]
    assert parse_gpa(bad).reconciled is False


def test_header_and_block_must_agree():
    lines = ["UGRD UNT Cumulative GPA: 3.100", "-- GPA (ALL COURSES)", "87.0ATTEMPTED HOURS 254.0POINTS 2.919AVG"]
    result = parse_gpa(lines)
    assert result.reconciled is False and "header" in result.note


def test_header_only_is_reported_but_not_reconciled():
    result = parse_gpa(["UGRD UNT Cumulative GPA: 3.250"])
    assert result.cumulative_gpa == 3.25 and result.reconciled is False


def test_no_gpa_at_all():
    assert parse_gpa(["nothing here"]) is None


def test_graduate_na_line_is_ignored():
    assert parse_gpa(["GRAD UNT Cumulative GPA: N/A"]) is None


def test_fixtures_describe_a_fictional_student():
    """The fixtures started as a real student's redacted audits. Grades and
    GPA were since replaced with fictional ones; this keeps the real figures
    from being reintroduced by a careless regeneration."""
    for path in FIXTURES.glob("*.txt"):
        text = path.read_text(encoding="utf-8")
        for real in ("2.712", "2.893", "236.0POINTS", "191.0POINTS", "2.500AVG", "3.257AVG", "2.264AVG", "2.461AVG"):
            assert real not in text, path.name
