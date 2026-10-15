"""
Cumulative GPA, as a UNT degree audit states it.

UNT audits print GPA twice: a header line ("UGRD UNT Cumulative GPA: 2.919")
and a requirement block that shows the arithmetic behind it:

    UNIVERSITY REQUIREMENTS FOR DEGREE -- GPA (ALL COURSES)
    ...
    87.0ATTEMPTED HOURS 254.0POINTS 2.919AVG

Fork doesn't compute GPA from the course list -- repeat rules, transfer work
and pass/fail grading make that a registrar's calculation, not ours. It reads
the figure the audit states and checks it two ways: the block's points over
attempted hours must give its average, and that average must match the
header. If either check fails the GPA is reported but marked unreconciled,
and the notebook won't treat it as a confirmed figure.
"""

import re

from pydantic import BaseModel

_HEADER = re.compile(r"UGRD\s+UNT\s+Cumulative\s+GPA:\s*(\d\.\d{1,3})\b", re.I)
_ALL_COURSES_BLOCK = re.compile(r"--\s*GPA\s*\(ALL COURSES\)", re.I)
_ARITHMETIC = re.compile(
    r"(\d+(?:\.\d+)?)\s*ATTEMPTED HOURS\s*(\d+(?:\.\d+)?)\s*POINTS\s*(\d\.\d{1,3})\s*AVG", re.I
)

#: UNT truncates GPA to three places rather than rounding it: 254 points
#: over 87 hours is 2.9195 and prints as 2.919, where rounding would give
#: 2.920. A small epsilon absorbs floating-point error at the edges.
_EPSILON = 1e-9


def _truncation_matches(points: float, hours: float, printed: float) -> bool:
    exact = points / hours
    return printed - _EPSILON <= exact < printed + 0.001 - _EPSILON


class AuditGpa(BaseModel):
    cumulative_gpa: float
    attempted_hours: float | None = None
    quality_points: float | None = None
    reconciled: bool = False
    note: str | None = None


def parse_gpa(lines: list[str]) -> AuditGpa | None:
    header = None
    for line in lines:
        match = _HEADER.search(line)
        if match:
            header = float(match.group(1))
            break

    block = None
    for i, line in enumerate(lines):
        if _ALL_COURSES_BLOCK.search(line):
            for following in lines[i + 1 : i + 6]:
                match = _ARITHMETIC.search(following)
                if match:
                    block = tuple(float(g) for g in match.groups())
                    break
            break

    if header is None and block is None:
        return None

    if block is None:
        return AuditGpa(
            cumulative_gpa=header,  # type: ignore[arg-type]
            reconciled=False,
            note="The audit states a GPA but not the hours and points behind it.",
        )

    hours, points, average = block
    arithmetic_ok = hours > 0 and _truncation_matches(points, hours, average)
    header_ok = header is None or abs(header - average) < 0.0005
    note = None
    if not arithmetic_ok:
        note = "The audit's grade points divided by attempted hours don't give its stated average."
    elif not header_ok:
        note = "The GPA in the audit's header doesn't match its GPA requirement block."
    return AuditGpa(
        cumulative_gpa=header if header is not None else average,
        attempted_hours=hours,
        quality_points=points,
        reconciled=arithmetic_ok and header_ok,
        note=note,
    )
