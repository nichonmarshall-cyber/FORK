"""
Parser tests: can Fork read a UNT degree audit?

Runs against text extracted from real audits with the identifying fields
replaced (see tools/redact_audit.py). The PDFs themselves are not in the
repository — they're education records.

These prove document reading only. Whether a course satisfies a requirement is
the matcher's question, tested separately against synthetic records, and
nothing here asserts anything about degree progress.
"""

from pathlib import Path

import pytest

from academic_record.enums import CompletionStatus, RequirementStatus, SpecialCode
from audit_import.unt.courses import classify, parse_course_row
from audit_import.unt.parser import UnsupportedDocument, parse_audit_text
from audit_import.unt.requirements import join_wrapped_lines
from audit_import.unt.text import AuditSections, strip_chrome

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def standard():
    return parse_audit_text(load("unt_audit_standard.txt"))


@pytest.fixture(scope="module")
def whatif():
    return parse_audit_text(load("unt_audit_whatif.txt"))


# --- Header metadata ---------------------------------------------------


def test_reads_program_and_catalog_year(standard):
    assert standard.program == "Bachelor of Science in Computer Science"
    assert standard.program_code == "ENBS CSCI"
    assert standard.catalog_year == "Fall 2024"
    assert standard.audit_prepared_at == "08/18/2026 03:18 PM"


def test_catalog_year_kept_verbatim(standard, whatif):
    """Stored as printed, not normalized into a catalog range.

    Mapping a term to a catalog is the resolver's job, and it has to be able to
    say it has no requirements for a given year rather than rounding to the
    nearest one it does have.
    """
    assert standard.catalog_year == "Fall 2024"
    assert whatif.catalog_year == "Fall 2026"


def test_evaluated_status_captured(standard):
    assert standard.audit_evaluated_status == "AT LEAST ONE REQUIREMENT IS NOT YET SATISFIED"


def test_what_if_detected_by_not_finalized_marker(standard, whatif):
    assert standard.is_what_if is False
    assert whatif.is_what_if is True
    assert any("What-If" in w for w in whatif.warnings)


def test_no_identifying_information_in_record(standard):
    """Fork has no use for a name or student ID, so it doesn't extract them.

    A record that never holds an identifier cannot leak one.
    """
    serialized = standard.model_dump_json()
    assert "Student ID" not in serialized
    assert "SAMPLE" not in serialized


# --- Canonical courses -------------------------------------------------


def test_courses_are_not_double_counted(standard):
    """Every course appears exactly once, though the document prints most of
    them two or three times.

    This is the invariant the whole parser is arranged around: the requirement
    analysis reprints courses to show placement, and reading those as courses
    inflates the total by roughly 2.3x.
    """
    keys = [c.key for c in standard.courses]
    assert len(keys) == len(set(keys))
    assert len(standard.courses) == 36


def test_completed_and_in_progress_hours(standard):
    assert standard.completed_hours == 81.0
    assert standard.in_progress_hours == 18.0


def test_in_progress_is_separate_from_completed(standard):
    in_progress = [
        c for c in standard.courses
        if c.completion_status == CompletionStatus.IN_PROGRESS
    ]
    assert in_progress
    assert all(not c.counts_toward_earned_hours for c in in_progress)
    assert all(c.special_code == SpecialCode.IN_PROGRESS for c in in_progress)


def test_subject_and_number_split(standard):
    course = next(c for c in standard.courses if c.subject == "CSCE" and c.number == "2110")
    assert course.hours == 3.0
    assert course.grade == "A"
    assert course.completion_status == CompletionStatus.COMPLETED


def test_course_number_keeps_trailing_letter(standard):
    """UCAR1000Z — the letter is part of the number, not a stray flag."""
    course = next(c for c in standard.courses if c.subject == "UCAR" and c.number == "1000Z")
    assert course.grade == "NP"
    assert course.completion_status == CompletionStatus.ATTEMPTED_NO_CREDIT


def test_zero_hour_and_failed_courses_recorded_not_dropped(standard):
    """A failed course still happened. Recording it keeps the record honest and
    stops it looking as though rows went missing."""
    internship = next(c for c in standard.courses if c.subject == "UCRS")
    assert internship.grade == "F"
    assert internship.completion_status == CompletionStatus.ATTEMPTED_NO_CREDIT
    assert internship.counts_toward_earned_hours is False


def test_term_code_preserved_and_decoded(standard):
    course = next(c for c in standard.courses if c.subject == "CSCE" and c.number == "4110")
    assert course.term_code == "26.8"
    assert course.term_label == "Fall 2026"


# --- Repeat and duplication codes --------------------------------------


def test_rx_rows_excluded_from_canonical_courses(standard):
    """UNT keeps repeat-excluded attempts out of COURSES BY ACADEMIC YEAR, so
    reading that section as canonical means RX can't inflate hours by
    construction rather than by a special case."""
    excluded_codes = {c.subject + c.number for c in standard.excluded_courses}
    assert excluded_codes == {"MATH1100", "PSCI2306"}
    assert all(c.special_code == SpecialCode.REPEAT_EXCLUDE for c in standard.excluded_courses)
    assert all(c.hours == 0.0 for c in standard.excluded_courses)
    assert all(not c.counts_toward_earned_hours for c in standard.excluded_courses)


def test_rc_row_counts_normally(standard):
    """Repeat-Count marks the attempt that does apply, so it defers to the
    grade like any ordinary row."""
    course = next(
        c for c in standard.courses
        if c.subject == "PSCI" and c.number == "2306" and c.special_code == SpecialCode.REPEAT_COUNT
    )
    assert course.grade == "A"
    assert course.hours == 3.0
    assert course.completion_status == CompletionStatus.COMPLETED
    assert course.counts_toward_earned_hours is True


def test_rx_outranks_a_passing_grade():
    """The ordering rule, stated directly.

    On a real audit RX rows carry an F and zero hours, so grade-first ordering
    happens to give the right answer. This asserts the rule that makes it right
    for the wrong reason impossible: the code decides, not the grade.
    """
    assert classify("A", SpecialCode.REPEAT_EXCLUDE) == CompletionStatus.NOT_COUNTED
    assert classify("A", SpecialCode.DUPLICATION) == CompletionStatus.NOT_COUNTED
    assert classify("A", SpecialCode.REPEAT_COUNT) == CompletionStatus.COMPLETED
    assert classify("A", None) == CompletionStatus.COMPLETED


def test_ip_outranks_a_grade():
    assert classify("B", SpecialCode.IN_PROGRESS) == CompletionStatus.IN_PROGRESS


def test_unreadable_grade_is_unknown_not_failed():
    """Two different statements. Not knowing whether credit was earned is not
    the same as knowing it wasn't, and neither counts toward hours."""
    assert classify(None, None) == CompletionStatus.UNKNOWN
    assert classify("F", None) == CompletionStatus.ATTEMPTED_NO_CREDIT


@pytest.mark.parametrize(
    "line, expected_code, expected_status",
    [
        # SYNTHETIC. DP and >R formatting has never been seen in a real UNT
        # export — these rows are constructed from UNT's documented behaviour
        # and the observed row layout. Passing does not mean the format is
        # confirmed. See FORMAT_VALIDATED_SPECIAL_CODES.
        ("25.1 HIST2610 3.0 A DP U S TO 1865", SpecialCode.DUPLICATION, CompletionStatus.NOT_COUNTED),
        ("25.1 MUSI1000 1.0 A >R APPLIED LESSONS", SpecialCode.REPEATABLE, CompletionStatus.COMPLETED),
    ],
)
def test_synthetic_dp_and_repeatable_rows(line, expected_code, expected_status):
    course = parse_course_row(line)
    assert course is not None
    assert course.special_code == expected_code
    assert course.completion_status == expected_status


# --- Reconciliation ----------------------------------------------------


def test_totals_reconcile_against_the_document(standard, whatif):
    """The audit states its own totals; summing the canonical list must
    reproduce them. This is what converts a silent misread into a visible
    'we can't confirm these figures'."""
    for record, completed, in_progress in ((standard, 81.0, 18.0), (whatif, 66.0, 24.0)):
        assert record.reconciliation.stated_completed_hours == completed
        assert record.reconciliation.stated_in_progress_hours == in_progress
        assert record.reconciliation.reconciled is True
    assert standard.warnings == []


def test_reconciliation_fails_loudly_when_a_row_is_misread():
    """Drop a course from the canonical section and the totals must stop
    agreeing. A check that can't fail isn't a check."""
    text = load("unt_audit_standard.txt")
    lines = text.split("\n")
    marker = next(i for i, l in enumerate(lines) if "COURSES BY ACADEMIC YEAR" in l)
    kept = [
        l for i, l in enumerate(lines)
        if not (i > marker and "CSCE1030" in l)
    ]
    record = parse_audit_text("\n".join(kept))

    assert record.reconciliation.reconciled is False
    assert record.completed_hours == 78.0
    assert any("did not reconcile" in w for w in record.warnings)


def test_reconciliation_is_false_when_totals_are_absent():
    """An unverified total is not a verified one. Missing stated figures leave
    the record unreconciled rather than assumed correct."""
    from academic_record.models import Reconciliation

    unchecked = Reconciliation(
        computed_completed_hours=81.0, computed_in_progress_hours=18.0
    )
    assert unchecked.reconciled is False
    assert unchecked.completed_matches is None


# --- Requirements ------------------------------------------------------


def test_requirement_blocks_detected(standard):
    assert len(standard.requirements) == 21
    titles = [r.title for r in standard.requirements]
    assert "MATHEMATICS: UNIVERSITY CORE -- 3 HOURS" in titles
    assert any(t.startswith("MAJOR IN COMPUTER SCIENCE (") for t in titles)


def test_requirement_status_derived_from_surviving_markers(standard):
    """UNT's OK / IP / NO / + / - glyphs don't survive the PDF export, so
    status comes from EARNED / NEEDS / IN PROGRESS — and the evidence is kept
    so the derivation can be checked."""
    core = next(r for r in standard.requirements if r.title.startswith("MATHEMATICS:"))
    assert core.status == RequirementStatus.COMPLETE
    assert core.hours_earned == 5.0
    assert core.status_evidence

    major = next(
        r for r in standard.requirements if r.title.startswith("MAJOR IN COMPUTER SCIENCE (")
    )
    assert major.status != RequirementStatus.COMPLETE
    assert major.subrequirements_needed == 5


def test_requirements_reference_courses_and_add_no_hours(standard):
    """Placements point at canonical courses. A requirement cannot contribute
    hours, only name them, so no amount of requirement-parsing error can move
    a total."""
    known = {c.key for c in standard.courses}
    placements = [
        p for r in standard.requirements for p in r.courses_applied
    ]
    assert placements
    resolved = [p for p in placements if p.course_key in known]
    assert len(resolved) > len(known)  # courses reprinted under requirements
    assert standard.completed_hours == 81.0


def test_subrequirements_segmented_on_trailing_markers(standard):
    """UNT numbers subrequirements from below: content, then `1)`. That
    trailing marker is an explicit delimiter, unlike the enclosing block."""
    major = next(
        r for r in standard.requirements if r.title.startswith("MAJOR IN COMPUTER SCIENCE (")
    )
    labels = [s.label for s in major.subrequirements if s.label]
    assert "1" in labels
    assert "OR" in labels  # the alternative path
    alternative = next(s for s in major.subrequirements if s.is_alternative)
    assert alternative.raw_lines


def test_select_from_rules_recorded_not_interpreted(standard):
    """A SELECT FROM line is evidence, not a decision. Deciding what satisfies
    it needs the catalog and belongs to the matcher."""
    major = next(
        r for r in standard.requirements if r.title.startswith("MAJOR IN COMPUTER SCIENCE (")
    )
    assert major.remaining_rule is not None
    assert "CSCE 3550" in major.remaining_rule


def test_header_confidence_recorded(standard):
    """Block boundaries are inferred, so how solid each one looked is part of
    the output rather than hidden."""
    confidences = {r.header_confidence for r in standard.requirements}
    assert confidences <= {"high", "low"}
    assert sum(1 for r in standard.requirements if r.header_confidence == "high") >= 18


# --- Text handling -----------------------------------------------------


def test_print_chrome_removed():
    lines = strip_chrome(load("unt_audit_standard.txt"))
    assert not any("uachieve.com" in l for l in lines)
    assert not any("My Audit - Audit Results Tab" in l for l in lines)
    assert not any("Open All Sections" in l for l in lines)


def test_wrapped_lines_rejoined():
    """UNT hard-wraps at about 56 characters. Left split, the fragments read as
    separate requirements."""
    joined = join_wrapped_lines([
        "COMPLETE SOFTWARE DEVELOPMENT CAPSTONE I AND II ('C' OR",
        "HIGHER):",
        "NEEDS:   6.0  HOURS",
    ])
    assert joined[0] == "COMPLETE SOFTWARE DEVELOPMENT CAPSTONE I AND II ('C' OR HIGHER):"
    assert joined[1] == "NEEDS:   6.0  HOURS"


def test_markers_never_absorbed_into_prose():
    joined = join_wrapped_lines([
        "A MINIMUM OF 42 ADVANCED SEMESTER HOURS IS REQUIRED FOR",
        "25.8 MATH1710 4.0 C CALCULUS I",
    ])
    assert len(joined) == 2


def test_sections_split_on_canonical_boundaries():
    sections = AuditSections(strip_chrome(load("unt_audit_standard.txt")))
    assert sections.has_canonical_course_section
    assert any("CSCE1030" in l for l in sections.by_academic_year)
    assert any("RX" in l for l in sections.duplicate_courses)
    assert not any("COURSES BY ACADEMIC YEAR" in l for l in sections.requirement_analysis)


# --- Failure modes -----------------------------------------------------


def test_non_audit_text_rejected_as_technical_failure():
    """A document Fork can't process is a real error. Distinct from one that
    parsed fine but left Fork unable to confirm something, which isn't."""
    with pytest.raises(UnsupportedDocument):
        parse_audit_text("This is a cover letter, not a degree audit.")


def test_empty_document_rejected():
    with pytest.raises(UnsupportedDocument):
        parse_audit_text("   \n\n   ")


def test_parsing_is_deterministic(standard):
    again = parse_audit_text(load("unt_audit_standard.txt"))
    assert again.model_dump_json() == standard.model_dump_json()


# --- Program agnosticism -----------------------------------------------


def test_parser_contains_no_program_specific_logic():
    """The parser understands the UNT document format and nothing about
    degrees. A branch on subject prefix or major name here would mean degree
    knowledge had leaked out of the catalog layer.
    """
    package = Path(__file__).resolve().parent.parent
    banned = ("CSCE", "computer_science", "COMPUTER SCIENCE", "PSYC", "MEEN", "psychology")

    for path in package.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.split("\n")
            if not line.strip().startswith("#")
        )
        # Strip docstrings — examples in prose are fine, branches are not.
        for marker in ('"""', "'''"):
            parts = code.split(marker)
            code = "".join(parts[::2]) if len(parts) > 2 else code
        for term in banned:
            assert term not in code, f"{path.name} references {term!r} outside comments"