"""
Reading a course row.

The shape UNT prints:

    23.8 ENGL1310      3.0  B         FIRST-YEAR WRITING I
    26.8 CSCE2610      3.0  EN IP     AL COMP ORG
    24.8 PSCI2306      3.0  A  RC     US AND TEXAS GOVT
    23.8 MATH1100      0.0  F  RX     ALGEBRA
    23.8 UCAR1000Z     0.0  NP        CAREER READINESS SEMINAR I

Term code, course, hours, then a short run of flags and a grade, then the
title. The flag run is the interesting part: `EN` marks current enrolment and
comes before everything, a grade may or may not be present, and a repeat code
may follow the grade.

The ordering rule is what makes this correct. A special code decides whether
hours count, and it decides that *before* the grade is consulted. `F RX` is
excluded because of the RX; it would still be excluded reading `A RX`. Reading
the grade first — taking the F, calling it not-earning, and moving on — happens
to give the right answer here and the wrong one elsewhere, which is the failure
mode this file exists to avoid.
"""

import re

from academic_record.enums import (
    NON_COUNTING_SPECIAL_CODES,
    ArticulationType,
    CompletionStatus,
    SpecialCode,
)
from academic_record.models import NormalizedCourse
from academic_record.provenance import extracted

#: Term code, subject, number, hours, remainder. The number keeps its trailing
#: letter (UCAR1000Z) because that letter is part of the course number.
COURSE_ROW = re.compile(
    r"^\s*(?P<term>\d{2}\.\d)\s+"
    r"(?P<subject>[A-Z]{2,5})(?P<number>\d{3,4}[A-Z]?)\s+"
    r"(?P<hours>\d+(?:\.\d+)?)\s+"
    r"(?P<rest>\S.*?)\s*$"
)

_PASSING_GRADES = {
    "A", "A+", "A-",
    "B", "B+", "B-",
    "C", "C+", "C-",
    "D", "D+", "D-",
    "P", "CR", "S",
}

_NON_EARNING_GRADES = {"F", "W", "WF", "NC", "U", "I", "NP", "WP"}

_ALL_GRADES = _PASSING_GRADES | _NON_EARNING_GRADES

#: Enrolment marker. Sits ahead of the IP code on in-progress rows.
_ENROLLED_FLAG = "EN"

_SPECIAL_BY_TOKEN = {code.value: code for code in SpecialCode}

#: Observed suffix mapping. Not documented by UNT — inferred from the reference
#: exports, where .1 rows are spring courses, .4 summer, .8 fall. Used for
#: display only; nothing calculates from it.
_TERM_SUFFIX = {"1": "Spring", "4": "Summer", "8": "Fall"}


def decode_term(term_code: str) -> str | None:
    """'26.8' -> 'Fall 2026'. None when the suffix isn't one we've seen."""
    try:
        year_part, suffix = term_code.split(".")
    except ValueError:
        return None
    season = _TERM_SUFFIX.get(suffix)
    if season is None:
        return None
    return f"{season} 20{year_part}"


def _split_flags(rest: str) -> tuple[str | None, SpecialCode | None, str, bool]:
    """Separate the flag run from the title.

    Returns (grade, special_code, title, enrolled). Consumes at most an `EN`,
    then a grade, then a special code — a bounded window, so a title beginning
    with a word that looks like a flag can't be eaten. Titles are short and
    UNT-abbreviated, and losing one to over-consumption would be silent.
    """
    tokens = rest.split()
    i = 0
    enrolled = False
    grade: str | None = None
    special: SpecialCode | None = None

    if i < len(tokens) and tokens[i] == _ENROLLED_FLAG:
        enrolled = True
        i += 1

    if i < len(tokens) and tokens[i] in _ALL_GRADES:
        grade = tokens[i]
        i += 1

    if i < len(tokens) and tokens[i] in _SPECIAL_BY_TOKEN:
        special = _SPECIAL_BY_TOKEN[tokens[i]]
        i += 1

    return grade, special, " ".join(tokens[i:]).strip(), enrolled


def classify(grade: str | None, special: SpecialCode | None) -> CompletionStatus:
    """Decide completion status, special code first.

    Order is the whole point:

      1. A code that suppresses credit (RX, DP) wins outright.
      2. IP means in progress whatever else is on the row.
      3. Only then does the grade get a say.

    RC is deliberately absent from steps 1 and 2 — it means this attempt is the
    one that counts, so it defers to the grade like any ordinary row.
    """
    if special in NON_COUNTING_SPECIAL_CODES:
        return CompletionStatus.NOT_COUNTED

    if special == SpecialCode.IN_PROGRESS:
        return CompletionStatus.IN_PROGRESS

    if grade is None:
        return CompletionStatus.UNKNOWN
    if grade in _PASSING_GRADES:
        return CompletionStatus.COMPLETED
    if grade in _NON_EARNING_GRADES:
        return CompletionStatus.ATTEMPTED_NO_CREDIT
    return CompletionStatus.UNKNOWN


def parse_course_row(line: str, source: str = "UNT Degree Audit") -> NormalizedCourse | None:
    """One line in, one course out, or None if the line isn't a course row."""
    match = COURSE_ROW.match(line)
    if match is None:
        return None

    grade, special, title, enrolled = _split_flags(match.group("rest"))

    # An in-progress row carries the enrolment flag but no grade. Recognising
    # that pairing means a future export that drops the explicit IP token still
    # classifies correctly rather than falling through to UNKNOWN.
    if special is None and enrolled and grade is None:
        special = SpecialCode.IN_PROGRESS

    term_code = match.group("term")

    return NormalizedCourse(
        subject=match.group("subject"),
        number=match.group("number"),
        title=title or None,
        hours=float(match.group("hours")),
        grade=grade,
        term_code=term_code,
        term_label=decode_term(term_code),
        completion_status=classify(grade, special),
        special_code=special,
        # Every row in both reference documents is UNT-native. Transfer
        # coursework would carry an institution marker this parser has never
        # seen, so claiming anything else here would be invention.
        articulation_type=ArticulationType.NOT_APPLICABLE,
        provenance=extracted(source),
        raw_line=line.strip(),
    )


def parse_course_rows(lines: list[str], source: str = "UNT Degree Audit") -> list[NormalizedCourse]:
    parsed = (parse_course_row(line, source) for line in lines)
    return [course for course in parsed if course is not None]