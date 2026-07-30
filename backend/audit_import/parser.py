"""
Extracts credit hours from a degree audit PDF.

No AI in here, on purpose. Audits are machine-generated, so the layout is
regular enough for regex, and the result can be unit tested. These numbers
feed straight into the cost engine — a wrong guess here becomes a wrong
dollar figure on screen.

Written to be school-agnostic rather than tied to one campus. The general
shape it looks for:

    SOME BLOCK NAME (58 HOURS)              <- requirement block
    24.8  CSCE1010  3.0  B  DISCOVERING CS  <- a course
    NEEDS: 6.0 HOURS                        <- still outstanding

Handles a term column in any format or missing entirely, 3- or 4-digit
course numbers, "CS 101" or "CS101", integer or decimal hours,
HOURS/CREDITS/CR/SCH, mixed-case headers, and tabs or spaces.

If a school's audit doesn't fit this shape at all, write a second parser
alongside this one rather than loosening these patterns further. Loose
enough and it stops parsing and starts guessing.

v1 reads hours only. Not handling prerequisite chains, and not trying to
work out which course satisfies a "SELECT FROM: CSCE 4901,4902" — those
count as hours still outstanding. That's a catalog problem, not a parsing
problem.

Whatever comes out of here is a proposal, not a fact. It goes into editable
fields for the student to confirm before the engine sees it.
"""

import re
from dataclasses import dataclass, field

# Grades that count as completed with hours earned.
_PASSING_GRADE_TOKENS = {
    "A", "A+", "A-",
    "B", "B+", "B-",
    "C", "C+", "C-",
    "D", "D+", "D-",
    "P", "CR", "S",
}

# Finished but earning no hours. Tracked separately rather than dropped so
# a failed course doesn't silently vanish from the totals.
_NON_EARNING_GRADE_TOKENS = {"F", "W", "WF", "NC", "U", "I"}

# "24.8  CSCE1010   3.0  B   DISCOVERING CS"
# "Fall 2024  CS 101   3  B   INTRO"
# "202480  MATH1710  4.0  A   CALCULUS I"
#
# The term column is optional and unconstrained in format, since every
# school does it differently and it's never used in a calculation. The row
# is anchored on the consistent part: course code, hours, then grade.
_COURSE_ROW = re.compile(
    r"^\s*(?P<term>.{0,12}?)\s*"
    r"\b(?P<subject>[A-Z]{2,5})\s?(?P<number>\d{3,4}[A-Z]?)\b"
    r"\s+(?P<hours>\d+(?:\.\d+)?)"
    r"\s+(?P<rest>\S.*?)\s*$"
)

# "MAJOR IN COMPUTER SCIENCE (58 HOURS)"
# "Major in Computer Science (58 credits)"
#
# The whole line has to be the header, otherwise a sentence like "...lab
# component (3 hours)..." gets read as a requirement block. The leading
# lookahead skips numbered requirement lines like "1) ...".
_BLOCK_HEADER = re.compile(
    r"^\s*(?!\d+\s*\))"
    r"(?P<label>[A-Za-z][A-Za-z0-9\s\-'&./]{3,}?)\s*"
    r"\(\s*(?P<hours>\d+(?:\.\d+)?)\s*(?:HOURS?|CREDITS?|CR|SCH)\s*\)\s*$",
    re.IGNORECASE,
)

# "NEEDS:   6.0  HOURS"
_NEEDS_HOURS = re.compile(
    r"NEEDS:\s*(?P<hours>\d+(?:\.\d+)?)\s*(?:HOURS?|CREDITS?|CR|SCH)\b",
    re.IGNORECASE,
)


@dataclass
class ParsedCourse:
    """A single course row from the audit."""
    term: str
    course: str
    hours: float
    grade: str
    status: str  # "complete" | "in_progress" | "not_earning"


@dataclass
class ParsedBlock:
    """One requirement block: a major, minor, core area, and so on."""
    label: str
    hours_required: float | None
    hours_completed: float = 0.0
    hours_in_progress: float = 0.0
    hours_declared_outstanding: float = 0.0
    courses: list[ParsedCourse] = field(default_factory=list)


@dataclass
class ParsedAudit:
    """Everything read successfully, plus warnings about what wasn't."""
    blocks: list[ParsedBlock] = field(default_factory=list)
    total_hours_completed: float = 0.0
    total_hours_in_progress: float = 0.0
    total_hours_not_earning: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def parsed_anything(self) -> bool:
        return bool(self.blocks) or self.total_hours_completed > 0


def _classify_row(rest: str) -> tuple[str, str]:
    """Determine (grade, status) from the tail end of a course row.

    Completed rows lead with a grade:  "B     DISCOVERING CS"
    In-progress rows carry an IP flag: "EN  IP  AL COMP ORG"
    """
    tokens = rest.split()
    leading = tokens[:3]  # grade/flags live at the front; title follows

    if any(t.upper() == "IP" for t in leading):
        return ("IP", "in_progress")

    for token in leading:
        upper = token.upper()
        if upper in _PASSING_GRADE_TOKENS:
            return (upper, "complete")
        if upper in _NON_EARNING_GRADE_TOKENS:
            return (upper, "not_earning")

    # Unrecognized. Counting it either way would be a guess, so skip it
    # and surface a warning instead.
    return ("", "unknown")


def parse_audit_text(text: str) -> ParsedAudit:
    """Text in, hour totals out. Same input always gives the same output.
    No file reads, no network, no model calls."""
    audit = ParsedAudit()
    current: ParsedBlock | None = None
    unknown_rows = 0

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        header = _BLOCK_HEADER.match(line)
        if header:
            current = ParsedBlock(
                label=header.group("label").strip().upper(),
                hours_required=float(header.group("hours")),
            )
            audit.blocks.append(current)
            continue

        row = _COURSE_ROW.match(line)
        if row:
            hours = float(row.group("hours"))
            grade, status = _classify_row(row.group("rest"))

            if status == "unknown":
                unknown_rows += 1
                continue

            course = ParsedCourse(
                term=row.group("term"),
                course=f'{row.group("subject")}{row.group("number")}',
                hours=hours,
                grade=grade,
                status=status,
            )

            if current is None:
                # Courses sometimes appear before any block header —
                # transfer credit, stray electives. Bucket them here
                # rather than dropping them.
                current = ParsedBlock(label="UNGROUPED", hours_required=None)
                audit.blocks.append(current)

            current.courses.append(course)

            if status == "complete":
                current.hours_completed += hours
                audit.total_hours_completed += hours
            elif status == "in_progress":
                current.hours_in_progress += hours
                audit.total_hours_in_progress += hours
            else:  # not_earning
                audit.total_hours_not_earning += hours
            continue

        needs = _NEEDS_HOURS.search(line)
        if needs and current is not None:
            current.hours_declared_outstanding += float(needs.group("hours"))
            continue

    if unknown_rows:
        audit.warnings.append(
            f"Could not read the grade column on {unknown_rows} course row(s), "
            "so they aren't included in any of these totals. Worth checking "
            "manually."
        )
    if not audit.blocks:
        audit.warnings.append(
            "No requirement blocks recognized. This audit is likely laid out "
            "differently than expected; enter your hours manually."
        )

    return audit


def parse_audit_pdf(file_bytes: bytes) -> ParsedAudit:
    """Extract the text from an audit PDF, then parse it.

    Never written to disk. An audit contains a student ID and a full course
    and grade history, and this application has no authentication, no
    encryption at rest, and no retention policy, so it doesn't get to keep
    one. Bytes in, numbers out, bytes discarded.
    """
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)

    audit = parse_audit_text(text)
    if not text.strip():
        audit.warnings.append(
            "No text layer in this PDF, so it's likely a scan. Enter your "
            "hours manually."
        )
    return audit


def propose_engine_inputs(audit: ParsedAudit) -> dict:
    """Turn a parsed audit into suggested inputs for the student to confirm.

    Each suggestion comes with the basis for it so the student can check it
    against their own records. Deliberately does not build a
    ChangeMajorInputs — confirmation comes first, then the engine.
    """
    return {
        "credits_completed": {
            "suggested": round(audit.total_hours_completed, 1),
            "basis": "Sum of hours from courses with a passing grade.",
        },
        "credits_in_progress": {
            "suggested": round(audit.total_hours_in_progress, 1),
            "basis": "Hours from courses marked in progress. Not counted as "
                     "completed.",
        },
        "credits_transferable": {
            "suggested": None,
            "basis": "Not available from an audit of your current major. This "
                     "needs a what-if audit run against the new major, or your "
                     "advisor's estimate. Note that credits which don't satisfy "
                     "a requirement in the new major often still count toward "
                     "your degree as electives.",
        },
        "blocks_detected": [
            {
                "label": b.label,
                "hours_required": b.hours_required,
                "hours_completed": round(b.hours_completed, 1),
                "hours_in_progress": round(b.hours_in_progress, 1),
                "hours_declared_outstanding": round(b.hours_declared_outstanding, 1),
            }
            for b in audit.blocks
        ],
        "warnings": audit.warnings,
    }
