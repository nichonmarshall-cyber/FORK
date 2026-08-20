"""
Turning a UNT audit PDF into lines worth parsing.

Two jobs: drop the browser print chrome, and split the document into the
sections that mean different things.

The chrome matters more than it sounds. The export is a printed web page, so
every page carries a timestamp header and a URL footer. They land on their own
lines, which makes them easy to remove — but only if they're removed before
anything tries to read block structure, because otherwise a requirement header
can end up separated from its block by three lines of navigation furniture.
"""

import re

#: "8/18/26, 3:20 PM My Audit - Audit Results Tab"
_PAGE_TIMESTAMP = re.compile(r"^\d{1,2}/\d{1,2}/\d{2},\s+\d{1,2}:\d{2}\s+[AP]M\s+My Audit")

#: The self-service URL plus its trailing "3/6" page counter.
_PAGE_URL = re.compile(r"^https?://\S*uachieve\S*")

#: Interface controls that print along with the content.
_UI_CHROME = re.compile(r"^\s*Open All Sections\s+Close All Sections\s*$")


def strip_chrome(text: str) -> list[str]:
    """Drop print headers, footers, and UI controls; return the rest as lines.

    Trailing whitespace goes too. pypdf pads several rows with it and leaving
    it in means every downstream pattern needs a `\\s*$` it shouldn't need.
    """
    kept = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        if _PAGE_TIMESTAMP.match(line):
            continue
        if _PAGE_URL.match(line):
            continue
        if _UI_CHROME.match(line):
            continue
        kept.append(line)
    return kept


#: Section markers. Everything above ADDITIONAL COURSES is requirement
#: analysis; everything below is the document's own summaries of the same
#: coursework, printed again.
_ADDITIONAL = re.compile(r"^\s*ADDITIONAL COURSES\s*$")
_DUPLICATE = re.compile(r"^\s*DUPLICATE COURSES\s*$")
_BY_YEAR = re.compile(r"^\s*COURSES BY ACADEMIC YEAR\s*$")
_END = re.compile(r"^\s*\*+\s*END OF ANALYSIS\s*\*+\s*$")


class AuditSections:
    """The document split by purpose.

    `by_academic_year` is the canonical course list. UNT prints every course
    there exactly once, and its hour totals reconcile against the figures the
    audit states about itself. The requirement analysis above it prints the
    same courses again, two or three times each, to show where they were
    applied — those are placements, not courses.

    `duplicate_courses` holds excluded repeat attempts. UNT has already zeroed
    their hours and left them out of the academic-year listing, so reading them
    is about preserving the student's history rather than about arithmetic.
    """

    def __init__(self, lines: list[str]):
        self.all_lines = lines
        idx_additional = _find(lines, _ADDITIONAL)
        idx_duplicate = _find(lines, _DUPLICATE)
        idx_by_year = _find(lines, _BY_YEAR)
        idx_end = _find(lines, _END)

        analysis_end = _first_present(
            [idx_additional, idx_duplicate, idx_by_year], default=len(lines)
        )

        self.requirement_analysis = lines[:analysis_end]
        self.additional_courses = _slice(lines, idx_additional, [idx_duplicate, idx_by_year, idx_end])
        self.duplicate_courses = _slice(lines, idx_duplicate, [idx_by_year, idx_end])
        self.by_academic_year = _slice(lines, idx_by_year, [idx_end])

    @property
    def has_canonical_course_section(self) -> bool:
        return bool(self.by_academic_year)


def _find(lines: list[str], pattern: re.Pattern) -> int | None:
    for i, line in enumerate(lines):
        if pattern.match(line):
            return i
    return None


def _first_present(indices: list[int | None], default: int) -> int:
    present = [i for i in indices if i is not None]
    return min(present) if present else default


def _slice(lines: list[str], start: int | None, enders: list[int | None]) -> list[str]:
    """Lines from just after `start` up to the earliest ender that follows it."""
    if start is None:
        return []
    after = [i for i in enders if i is not None and i > start]
    end = min(after) if after else len(lines)
    return lines[start + 1 : end]