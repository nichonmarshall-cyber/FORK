"""
The metadata block at the top of a UNT audit.

    SAMPLE,STUDENT A
    Bachelor of Science in Computer Science - College of Engineering
    Prepared On Program Code Catalog Year Student ID Job ID
    08/18/2026 03:18 PM ENBS CSCI Fall 2024 00000000 0000000000000000

Column labels on one line, values on the next, aligned by position in the
original HTML table and separated by nothing but spaces once it reaches text.
Three of the five values contain spaces themselves, so splitting on whitespace
gives six or seven fields with no reliable way to tell which belong together.

The values are read by shape instead: a date, a time with a meridiem, then
program-code tokens, then a season and year, then two runs of digits. Each
piece is distinctive enough that the whole row matches in one pass or not at
all — better than a positional guess that silently mis-assigns a field.

Student name and ID are not extracted. Fork has no use for either, and a
record that never holds them cannot leak them.
"""

import re

#: What-If exports replace the college name with this marker.
WHAT_IF_MARKER = "NOT FINALIZED"

_PROGRAM_LINE = re.compile(
    r"^(?P<degree>(?:Bachelor|Master|Doctor)\b[^-]*?)\s*-\s*(?P<suffix>.+?)\s*$"
)

_HEADER_LABELS = re.compile(r"Prepared On\s+Program Code\s+Catalog Year")

_HEADER_VALUES = re.compile(
    r"^\s*(?P<prepared>\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)\s+"
    r"(?P<program_code>[A-Z0-9]+(?:\s+[A-Z0-9]+)?)\s+"
    r"(?P<catalog_year>(?:Fall|Spring|Summer|Winter)\s+\d{4})\s+"
    r"(?P<student_id>\d+)\s+(?P<job_id>\d+)\s*$"
)

_EVALUATED_STATUS = re.compile(r"^\*{3}\s*(?P<text>.+?)\s*\*{3}$")


class AuditHeader:
    def __init__(self) -> None:
        self.program: str | None = None
        self.program_code: str | None = None
        self.catalog_year: str | None = None
        self.audit_prepared_at: str | None = None
        self.audit_evaluated_status: str | None = None
        self.is_what_if: bool = False
        self.warnings: list[str] = []


def parse_header(lines: list[str], scan_limit: int = 40) -> AuditHeader:
    """Read metadata from the top of the document.

    Only the first `scan_limit` lines are searched. The header is always at the
    top, and scanning the whole document risks matching a course title or a
    requirement description that happens to look like a program line.
    """
    header = AuditHeader()
    window = lines[:scan_limit]

    for i, line in enumerate(window):
        program_match = _PROGRAM_LINE.match(line)
        if program_match and header.program is None:
            suffix = program_match.group("suffix")
            header.program = program_match.group("degree").strip()
            # The suffix is normally the college. On a What-If it's the
            # not-finalized banner instead, which is the only structural
            # difference between the two export types.
            if WHAT_IF_MARKER in suffix.upper():
                header.is_what_if = True
            continue

        if _HEADER_LABELS.search(line):
            # Values are on the following line. Look there rather than
            # assuming a fixed offset from the top of the page.
            if i + 1 < len(window):
                values = _HEADER_VALUES.match(window[i + 1])
                if values:
                    header.audit_prepared_at = _normalize_spaces(values.group("prepared"))
                    header.program_code = _normalize_spaces(values.group("program_code"))
                    header.catalog_year = _normalize_spaces(values.group("catalog_year"))
                else:
                    header.warnings.append(
                        "Header value row did not match the expected shape: "
                        f"{window[i + 1]!r}"
                    )
            continue

        status_match = _EVALUATED_STATUS.match(line.strip())
        if status_match and header.audit_evaluated_status is None:
            header.audit_evaluated_status = status_match.group("text")

    if not header.is_what_if and any(
        WHAT_IF_MARKER in line.upper() for line in window
    ):
        header.is_what_if = True

    for field in ("program", "program_code", "catalog_year", "audit_prepared_at"):
        if getattr(header, field) is None:
            header.warnings.append(f"Could not read {field} from the document header.")

    return header


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()