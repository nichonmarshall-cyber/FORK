"""
Requirement blocks, and the status of each.

Three properties of this section shape the approach.

**Text is hard-wrapped.** UNT breaks prose at roughly 56 characters, so one
logical line arrives as two or three physical ones. `COMPLETE SOFTWARE
DEVELOPMENT CAPSTONE I AND II ('C' OR` / `HIGHER):` is a single sentence.
Classifying physical lines directly reads the fragments as separate
requirements, so the first pass rejoins them.

**Subrequirements are numbered from below.** The number trails its content:
description, then course rows, then `1)` alone on a line. That trailing marker
is an explicit delimiter, which makes subrequirement segmentation structural
rather than heuristic — the one part of this file that isn't inference.

**Block boundaries are not marked at all.** Nothing separates one top-level
requirement from the next, and body text is upper case exactly like headings.
The detector looks for punctuation UNT reserves for headers and records how
strong the signal was. It is right on both reference documents and will
eventually meet one where it isn't, so every block keeps its source lines.

None of this uncertainty reaches credit totals. Requirements reference courses
by key and can only point at hours the canonical list already counted.
"""

import re

from academic_record.enums import RequirementStatus
from academic_record.models import (
    AuditRequirement,
    RequirementPlacement,
    Subrequirement,
)

from .courses import COURSE_ROW, parse_course_row

_EARNED_HOURS = re.compile(r"^\s*EARNED:\s*(?P<hours>\d+(?:\.\d+)?)\s*HOURS", re.I)
_EARNED_SUBREQS = re.compile(r"^\s*EARNED:\s*(?P<count>\d+)\s*SUB-REQTS", re.I)
_NEEDS_HOURS = re.compile(r"^\s*NEEDS:\s*(?P<hours>\d+(?:\.\d+)?)\s*HOURS", re.I)
_NEEDS_SUBREQS = re.compile(r"^\s*NEEDS:\s*(?P<count>\d+)\s*SUB-REQTS", re.I)
_IN_PROGRESS = re.compile(r"^\s*IN PROGRESS:\s*(?P<hours>\d+(?:\.\d+)?)\s*HOURS", re.I)
_IP_HOURS = re.compile(r"^\s*IP HOURS:\s*(?P<hours>\d+(?:\.\d+)?)\s*HOURS", re.I)
_HOURS_ADDED = re.compile(r"^\s*\d+(?:\.\d+)?\s*HOURS\s+(?:ADDED|TAKEN)", re.I)
_ATTEMPTED = re.compile(r"^\s*\d+(?:\.\d+)?\s*ATTEMPTED HOURS", re.I)
_SELECT_FROM = re.compile(r"^\s*SELECT FROM:\s*(?P<rule>.+?)\s*$", re.I)
_NOTE = re.compile(r"^\s*NOTE:", re.I)

#: Subrequirement numbering, trailing its content. `OR)` marks an alternative
#: path rather than the next sequential item.
_SUBREQ_NUMBER = re.compile(r"^\s*(?P<label>\d+|OR)\)\s*$")

_BANNER = re.compile(r"^\s*\*{3,}|^\s*-{3,}")

#: UNT wraps prose at about this width. A line at or past it that doesn't close
#: a sentence is almost certainly continued below.
_WRAP_WIDTH = 44

#: A short heading ending in a colon introduces its own continuation:
#: "MAJOR IN COMPUTER SCIENCE:" / "REQUIRED COURSES IN LABORATORY SCIENCE".
_SHORT_HEADING = 40


def _is_marker(line: str) -> bool:
    """Structural lines, which never merge into surrounding prose."""
    return bool(
        _EARNED_HOURS.match(line)
        or _EARNED_SUBREQS.match(line)
        or _NEEDS_HOURS.match(line)
        or _NEEDS_SUBREQS.match(line)
        or _IN_PROGRESS.match(line)
        or _IP_HOURS.match(line)
        or _HOURS_ADDED.match(line)
        or _ATTEMPTED.match(line)
        or _SELECT_FROM.match(line)
        or _NOTE.match(line)
        or _SUBREQ_NUMBER.match(line)
        or _BANNER.match(line)
        or COURSE_ROW.match(line)
    )


#: "UNIVERSITY REQUIREMENTS FOR DEGREE -- RESIDENCY HOURS". Requires real text
#: before the dash, so a continuation opening "-- COMPLETION OF..." can't match.
_DASHED_HEADING = re.compile(r"^[A-Z][A-Z0-9 &/,.'()]{4,}\s+-{1,2}\s+\S")

#: "COMMUNICATION (ENGLISH COMP. & RHETORIC): UNIVERSITY CORE"
_CORE_HEADING = re.compile(r":\s*UNIVERSITY CORE\b", re.I)

#: "MAJOR IN COMPUTER SCIENCE (58 HOURS)" — matches the shape, not the subject,
#: so it works for any program.
_HOURS_HEADING = re.compile(r"\(\d+\s+HOURS\)\s*$", re.I)

#: Structural openers introducing a named block in any UNT program.
#: Requires whitespace after the opening word. UNT writes block names as
#: "MAJOR IN PSYCHOLOGY (42 HOURS)" and "MAJOR RESIDENCY REQUIREMENT..." --
#: but its prose also contains "MAJOR/MINOR/CONCENTRATION, AS WELL AS...",
#: a mid-sentence fragment that a bare ^MAJOR would promote to a block.
_BLOCK_OPENER = re.compile(
    r"^(?:MAJOR|MINOR|CONCENTRATION|CERTIFICATE)\s|"
    r"^REQUIRED\b.*\bMAJORS?\b|"
    r"^ADDITIONAL REQUIREMENTS\b",
    re.I,
)


def _looks_like_heading(line: str) -> bool:
    """Whether a line carries punctuation UNT reserves for block headings.

    Used by the wrap-joiner to leave headings intact. Defined here rather than
    reusing `_is_probable_header` because that one also accepts short bare
    capitalised lines, which are exactly the lines most likely to be genuine
    wrapped prose.
    """
    stripped = line.strip()
    return bool(
        _CORE_HEADING.search(stripped)
        or _HOURS_HEADING.search(stripped)
        or _BLOCK_OPENER.match(stripped)
        or _DASHED_HEADING.match(stripped)
    )


def join_wrapped_lines(lines: list[str]) -> list[str]:
    """Rebuild logical lines from UNT's hard-wrapped output.

    Structural lines never join to anything: a course row or an EARNED marker
    means the prose above it has ended, whatever width it reached.
    """
    joined: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if not joined or _is_marker(stripped) or _is_marker(joined[-1]):
            joined.append(stripped)
            continue

        previous = joined[-1]

        # A heading is a complete line even when it runs long. Joining the
        # sentence beneath it into the title would bury the requirement's name
        # in a paragraph of catalog prose.
        if _looks_like_heading(previous):
            joined.append(stripped)
            continue

        # And a heading is never a continuation of whatever sits above it. A
        # long line that doesn't close a sentence usually wraps -- but if the
        # NEXT line opens a block, the wrap ended and the block begins.
        #
        # Without this, one unrecognised banner swallows the heading beneath
        # it and the whole block vanishes: its hours are never parsed, the
        # resolver finds no degree total, and a confirmed What-If silently
        # supplies nothing while the student's manual estimate survives. That
        # failure reaches the student as a correct-sounding sentence about
        # student-reported figures, which is close to undiagnosable from the
        # output alone.
        if _looks_like_heading(stripped):
            joined.append(stripped)
            continue

        wrapped = len(previous) >= _WRAP_WIDTH and not previous.endswith((".", "!"))
        heading_continues = previous.endswith(":") and len(previous) < _SHORT_HEADING

        if wrapped or heading_continues:
            joined[-1] = f"{previous} {stripped}"
        else:
            joined.append(stripped)

    return joined


_SENTENCE_OPENERS = (
    "A MINIMUM", "AT LEAST", "YOU MUST", "YOU MAY", "COMPLETION", "THIS ",
    "IF YOU", "SEE YOUR", "GRADE OF", "A MAXIMUM", "REPEATED", "COURSES WHERE",
    "AS OF", "BASED ON", "COMPLETE ", "NOTE", "(",
)

_SECTION_WORDS = ("ELECTIVE HOURS", "END OF ANALYSIS", "ALL ELECTIVES COMPLETED")


def _is_probable_header(line: str) -> tuple[bool, str]:
    """Decide whether a logical line opens a top-level requirement block.

    Returns (is_header, confidence). `high` means the line carries punctuation
    UNT reserves for headings. `low` means it is a short capitalised line that
    looks like one. The distinction is recorded rather than resolved, so a
    caller can weigh a block by how solid its boundary was.
    """
    stripped = line.strip()

    if not stripped or _is_marker(stripped):
        return False, "low"
    if any(word in stripped.upper() for word in _SECTION_WORDS):
        return False, "low"

    letters = [c for c in stripped if c.isalpha()]
    if not letters or not all(c.isupper() for c in letters):
        return False, "low"
    if any(stripped.upper().startswith(opener) for opener in _SENTENCE_OPENERS):
        return False, "low"

    if _CORE_HEADING.search(stripped) or _HOURS_HEADING.search(stripped):
        return True, "high"
    if _BLOCK_OPENER.match(stripped) or _DASHED_HEADING.match(stripped):
        return True, "high"

    # A short capitalised line that isn't a sentence — "TECHNICAL WRITING".
    # Kept deliberately tight: at four words or more this starts matching
    # subrequirement descriptions, which are not blocks.
    if len(stripped.split()) <= 3 and not stripped.endswith("."):
        return True, "low"

    return False, "low"


def _derive_status(requirement: AuditRequirement) -> RequirementStatus:
    """Determine whether a requirement is satisfied, from the markers that
    survive the PDF export.

    UNT's own OK / IP / NO / + / - glyphs are absent here, so this reads
    EARNED, NEEDS, IN PROGRESS and IP HOURS instead.

    Outstanding work outranks completed work: a block showing both EARNED and
    NEEDS is partly done, not finished. In-progress applies only when nothing
    is outstanding, since coursework underway doesn't close a gap that remains
    after it ends.
    """
    needs_something = bool(requirement.hours_needed) or bool(
        requirement.subrequirements_needed
    )
    has_progress = bool(requirement.hours_in_progress)
    has_earned = bool(requirement.hours_earned) or bool(
        requirement.subrequirements_earned
    )

    if needs_something:
        return (
            RequirementStatus.IN_PROGRESS
            if has_progress
            else RequirementStatus.UNFULFILLED
        )
    if has_earned:
        return RequirementStatus.COMPLETE
    if has_progress:
        return RequirementStatus.IN_PROGRESS
    return RequirementStatus.UNKNOWN


def _record_marker(requirement: AuditRequirement, line: str) -> bool:
    """Attach an EARNED / NEEDS / IN PROGRESS figure to the current block.

    Markers are attributed to the nearest preceding header. In the printed
    layout they float to the right of their block, so extraction can place them
    ahead of the subrequirements they summarise rather than after — which is
    why `status_evidence` keeps the line for inspection.

    Figures accumulate rather than overwrite: a block may report hours more than
    once, and keeping only the last would silently discard the rest.
    """
    for pattern, field, cast in (
        (_EARNED_HOURS, "hours_earned", float),
        (_NEEDS_HOURS, "hours_needed", float),
        (_IN_PROGRESS, "hours_in_progress", float),
        (_IP_HOURS, "hours_in_progress", float),
        (_EARNED_SUBREQS, "subrequirements_earned", int),
        (_NEEDS_SUBREQS, "subrequirements_needed", int),
    ):
        match = pattern.match(line)
        if not match:
            continue
        value = cast(next(iter(match.groupdict().values())))
        existing = getattr(requirement, field)
        setattr(requirement, field, value if existing is None else existing + value)
        requirement.status_evidence.append(line.strip())
        return True
    return False


def parse_requirements(lines: list[str]) -> list[AuditRequirement]:
    """Read requirement blocks out of the analysis section.

    Course rows here become placements referencing the canonical course list,
    never courses in their own right. That is what stops a course printed under
    three requirements from being counted three times.
    """
    logical = join_wrapped_lines(lines)

    requirements: list[AuditRequirement] = []
    current: AuditRequirement | None = None
    pending: list[str] = []
    pending_placements: list[RequirementPlacement] = []
    pending_rule: str | None = None

    def close_subrequirement(label: str) -> None:
        nonlocal pending, pending_placements, pending_rule
        if current is not None and (pending or pending_placements):
            description = next((line for line in pending if not _is_marker(line)), None)
            current.subrequirements.append(
                Subrequirement(
                    label=label,
                    description=description,
                    courses_applied=list(pending_placements),
                    remaining_rule=pending_rule,
                    raw_lines=list(pending),
                )
            )
        pending = []
        pending_placements = []
        pending_rule = None

    for line in logical:
        is_header, confidence = _is_probable_header(line)

        # Nothing counts until the first unambiguous heading. Above it sits the
        # document's metadata block — student name, GPA lines, catalog warning
        # — some of which is short and capitalised enough to look like a
        # heading on its own.
        if current is None and not (is_header and confidence == "high"):
            continue

        if is_header:
            close_subrequirement(label="")
            current = AuditRequirement(
                title=line.strip(),
                header_confidence=confidence,
                raw_lines=[line.strip()],
            )
            requirements.append(current)
            continue

        if current is None:
            continue

        current.raw_lines.append(line.strip())

        number = _SUBREQ_NUMBER.match(line)
        if number:
            close_subrequirement(label=number.group("label"))
            continue

        pending.append(line.strip())

        course = parse_course_row(line)
        if course is not None:
            placement = RequirementPlacement(course_key=course.key, raw_line=line.strip())
            current.courses_applied.append(placement)
            pending_placements.append(placement)
            continue

        select = _SELECT_FROM.match(line)
        if select:
            rule = select.group("rule")
            pending_rule = rule if pending_rule is None else f"{pending_rule}; {rule}"
            current.remaining_rule = (
                rule
                if current.remaining_rule is None
                else f"{current.remaining_rule}; {rule}"
            )
            continue

        _record_marker(current, line)

    close_subrequirement(label="")

    for requirement in requirements:
        requirement.status = _derive_status(requirement)

    return requirements