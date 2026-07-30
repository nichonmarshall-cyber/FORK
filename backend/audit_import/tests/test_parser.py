import os

import pytest

from ..parser import parse_audit_text, propose_engine_inputs

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "sample_audit.txt")


@pytest.fixture
def sample_text():
    with open(SAMPLE_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def parsed(sample_text):
    return parse_audit_text(sample_text)


def test_detects_both_requirement_blocks(parsed):
    labels = [b.label for b in parsed.blocks]
    assert "MAJOR IN COMPUTER SCIENCE" in labels
    assert "UNIVERSITY CORE CURRICULUM" in labels


def test_reads_required_hours_from_block_headers(parsed):
    by_label = {b.label: b for b in parsed.blocks}
    assert by_label["MAJOR IN COMPUTER SCIENCE"].hours_required == 58.0
    assert by_label["UNIVERSITY CORE CURRICULUM"].hours_required == 42.0


def test_sums_completed_hours_in_major_block(parsed):
    """Graded rows in the CS block total 19.0 (3+1+3+3+3+3+3). The three
    in-progress rows are excluded."""
    major = next(b for b in parsed.blocks if b.label == "MAJOR IN COMPUTER SCIENCE")
    assert major.hours_completed == 19.0


def test_in_progress_hours_are_tracked_separately_not_as_completed(parsed):
    """Three in-progress courses at 3.0 each is 9.0. These can never land in
    the completed total, since a course still underway isn't earned yet."""
    major = next(b for b in parsed.blocks if b.label == "MAJOR IN COMPUTER SCIENCE")
    assert major.hours_in_progress == 9.0
    assert parsed.total_hours_in_progress == 9.0


def test_totals_across_all_blocks(parsed):
    """Major 19.0 plus core 14.0 is 33.0 completed."""
    assert parsed.total_hours_completed == 33.0


def test_reads_explicitly_declared_outstanding_hours(parsed):
    by_label = {b.label: b for b in parsed.blocks}
    assert by_label["MAJOR IN COMPUTER SCIENCE"].hours_declared_outstanding == 6.0
    assert by_label["UNIVERSITY CORE CURRICULUM"].hours_declared_outstanding == 3.0


def test_select_from_lines_do_not_become_courses(parsed):
    """"SELECT FROM: CSCE 3550" is an unmet requirement with options, not a
    completed course, so it can't count as earned hours."""
    all_courses = [c.course for b in parsed.blocks for c in b.courses]
    assert "CSCE3550" not in all_courses
    assert "CSCE4010" not in all_courses
    assert "CSCE4901" not in all_courses


def test_course_details_are_captured(parsed):
    major = next(b for b in parsed.blocks if b.label == "MAJOR IN COMPUTER SCIENCE")
    intro = next(c for c in major.courses if c.course == "CSCE1030")
    assert intro.hours == 3.0
    assert intro.grade == "A"
    assert intro.status == "complete"


def test_failing_grades_do_not_earn_hours():
    text = (
        "MAJOR IN PSYCHOLOGY (40 HOURS)\n"
        "       25.4  PSYC1630          3.0  F     INTRO PSYCH\n"
        "       25.8  PSYC1630          3.0  B     INTRO PSYCH\n"
    )
    result = parse_audit_text(text)
    assert result.total_hours_completed == 3.0
    assert result.total_hours_not_earning == 3.0


def test_unrecognized_rows_are_warned_not_guessed():
    """A row that can't be classified gets excluded and reported, rather
    than guessed at in either direction."""
    text = (
        "MAJOR IN NURSING (60 HOURS)\n"
        "       25.4  NURS1000          3.0  ???   MYSTERY COURSE\n"
    )
    result = parse_audit_text(text)
    assert result.total_hours_completed == 0.0
    assert any("grade column" in w for w in result.warnings)


def test_unparseable_document_warns_rather_than_returning_zeros():
    result = parse_audit_text("This is not a degree audit at all.")
    assert not result.parsed_anything
    assert any("requirement blocks" in w for w in result.warnings)


def test_proposal_never_guesses_transferable_credits(parsed):
    """Transferable credits can't be derived from an audit of the current
    major. The proposal has to say so rather than invent a number."""
    proposal = propose_engine_inputs(parsed)
    assert proposal["credits_transferable"]["suggested"] is None
    assert "what-if audit" in proposal["credits_transferable"]["basis"]


def test_proposal_separates_completed_from_in_progress(parsed):
    proposal = propose_engine_inputs(parsed)
    assert proposal["credits_completed"]["suggested"] == 33.0
    assert proposal["credits_in_progress"]["suggested"] == 9.0


def test_proposal_carries_basis_for_every_suggested_value(parsed):
    """Same rule as the engine: no value without a stated basis for it."""
    proposal = propose_engine_inputs(parsed)
    for key in ["credits_completed", "credits_in_progress", "credits_transferable"]:
        assert proposal[key]["basis"], f"{key} is missing a basis"


# --- Format tolerance -------------------------------------------------
# Each case is the same single course written the way a different audit
# system might print it. All must come out as 3.0 completed hours and 58
# required. If one starts failing, the parser has quietly become
# school-specific again.

_ONE_COURSE_VARIANTS = {
    "column_aligned": "MAJOR IN COMPUTER SCIENCE (58 HOURS)\n   24.8  CSCE1010   3.0  B   DISCOVERING CS\n",
    "term_as_season_year": "MAJOR IN COMPUTER SCIENCE (58 HOURS)\n   Fall 2024  CSCE1010   3.0  B   DISCOVERING CS\n",
    "term_as_numeric_code": "MAJOR IN COMPUTER SCIENCE (58 HOURS)\n   202480  CSCE1010   3.0  B   DISCOVERING CS\n",
    "no_term_column": "MAJOR IN COMPUTER SCIENCE (58 HOURS)\n   CSCE1010   3.0  B   DISCOVERING CS\n",
    "three_digit_course": "MAJOR IN COMPUTER SCIENCE (58 HOURS)\n   24.8  CS101   3.0  B   INTRO\n",
    "course_code_with_space": "MAJOR IN COMPUTER SCIENCE (58 HOURS)\n   24.8  CSCE 1010   3.0  B   DISCOVERING CS\n",
    "course_with_trailing_letter": "MAJOR IN COMPUTER SCIENCE (58 HOURS)\n   24.8  CS101A   3.0  B   INTRO\n",
    "integer_hours": "MAJOR IN COMPUTER SCIENCE (58 HOURS)\n   24.8  CSCE1010   3  B   DISCOVERING CS\n",
    "plus_minus_grade": "MAJOR IN COMPUTER SCIENCE (58 HOURS)\n   24.8  CSCE1010   3.0  B+  DISCOVERING CS\n",
    "unit_says_credits": "MAJOR IN COMPUTER SCIENCE (58 CREDITS)\n   24.8  CSCE1010   3.0  B   DISCOVERING CS\n",
    "mixed_case_header": "Major in Computer Science (58 hours)\n   24.8  CSCE1010   3.0  B   DISCOVERING CS\n",
    "tab_separated": "MAJOR IN COMPUTER SCIENCE (58 HOURS)\n\t24.8\tCSCE1010\t3.0\tB\tDISCOVERING CS\n",
    "spaces_collapsed": "MAJOR IN COMPUTER SCIENCE (58 HOURS)\n24.8 CSCE1010 3.0 B DISCOVERING CS\n",
}


@pytest.mark.parametrize("variant", sorted(_ONE_COURSE_VARIANTS))
def test_layout_variations_all_yield_the_same_hours(variant):
    result = parse_audit_text(_ONE_COURSE_VARIANTS[variant])
    assert result.total_hours_completed == 3.0, f"{variant} lost the course row"
    assert result.blocks, f"{variant} lost the block header"
    assert result.blocks[0].hours_required == 58.0, f"{variant} lost required hours"


# --- False positives --------------------------------------------------
# Looser patterns are only safe if ordinary prose still fails to match. A
# parser that invents credit hours out of a sentence is worse than one that
# finds none.

_TRAP_LINES = {
    "prose_listing_course_numbers":
        "A MAXIMUM OF 6 HOURS CREDIT IN CSCE 2900, 4890, 4920,\n4940 OR 4950 WILL COUNT TOWARD THIS DEGREE.\n",
    "select_from_single_course":
        "MAJOR IN X (30 HOURS)\n   SELECT FROM:  CSCE 3550\n",
    "select_from_course_list":
        "MAJOR IN X (30 HOURS)\n   SELECT FROM:  CSCE 4901,4902\n",
    "sentence_containing_hours_in_parens":
        "You must complete a lab component (3 hours) before enrolling.\n",
    "numbered_requirement_line":
        "MAJOR IN X (30 HOURS)\n   1) DISCOVERING COMPUTER SCIENCE COMPLETE ('C' OR HIGHER).\n",
    "grade_policy_note":
        "MAJOR IN X (30 HOURS)\n   GRADE OF 'C' OR HIGHER ON EACH COURSE REQUIRED.\n",
}


@pytest.mark.parametrize("trap", sorted(_TRAP_LINES))
def test_prose_never_becomes_earned_hours(trap):
    result = parse_audit_text(_TRAP_LINES[trap])
    assert result.total_hours_completed == 0.0, f"{trap} produced phantom hours"
    courses = [c.course for b in result.blocks for c in b.courses]
    assert courses == [], f"{trap} produced phantom courses: {courses}"


def test_sentence_with_parenthetical_hours_is_not_a_requirement_block():
    result = parse_audit_text("You must complete a lab component (3 hours) before enrolling.\n")
    assert result.blocks == []
