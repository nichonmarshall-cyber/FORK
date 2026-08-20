"""
Checking the parser against the document.

A UNT audit states its own totals. Summing the canonical course list has to
reproduce them, and if it doesn't, something was misread — a row skipped, a
special code missed, a section boundary in the wrong place. The check costs
nothing and it converts a whole class of silent wrong answers into a visible
"we can't confirm this".

Only the reconciled case is trusted. A document whose stated totals couldn't be
found is not a document that agrees with us; it's one we have no way to check,
and the caller should treat those the same way.
"""

import re

from academic_record.models import NormalizedCourse, Reconciliation
from academic_record.enums import CompletionStatus

#: Bottom-of-document summary, distinguished by its GPA suffix. Preferred over
#: the block-level figures because it is unambiguously about the whole record.
_EARNED_SUMMARY = re.compile(
    r"^\s*EARNED:\s*(?P<hours>\d+(?:\.\d+)?)\s*HOURS\s+[\d.]+\s*AVG", re.I
)

_EARNED_ANY = re.compile(r"^\s*EARNED:\s*(?P<hours>\d+(?:\.\d+)?)\s*HOURS", re.I)

#: Distinct from `IP HOURS:`, which is a per-block figure.
_IN_PROGRESS_TOTAL = re.compile(
    r"^\s*IN PROGRESS:\s*(?P<hours>\d+(?:\.\d+)?)\s*HOURS", re.I
)


def find_stated_totals(lines: list[str]) -> tuple[float | None, float | None]:
    """Pull the totals the audit states about itself.

    Earned comes from the GPA-suffixed summary line when present. Failing that,
    the largest EARNED figure in the document is used: block totals are parts
    of the whole, so the maximum is the document total. That is a fallback, and
    if it disagrees with the computed sum the record says so rather than
    assuming the fallback was right.
    """
    earned: float | None = None
    earned_candidates: list[float] = []
    in_progress_candidates: list[float] = []

    for line in lines:
        summary = _EARNED_SUMMARY.match(line)
        if summary:
            earned = float(summary.group("hours"))
            continue

        any_earned = _EARNED_ANY.match(line)
        if any_earned:
            earned_candidates.append(float(any_earned.group("hours")))

        in_progress = _IN_PROGRESS_TOTAL.match(line)
        if in_progress:
            in_progress_candidates.append(float(in_progress.group("hours")))

    if earned is None and earned_candidates:
        earned = max(earned_candidates)

    return earned, (max(in_progress_candidates) if in_progress_candidates else None)


def reconcile(courses: list[NormalizedCourse], lines: list[str]) -> Reconciliation:
    computed_completed = round(
        sum(c.hours for c in courses if c.counts_toward_earned_hours), 1
    )
    computed_in_progress = round(
        sum(
            c.hours
            for c in courses
            if c.completion_status == CompletionStatus.IN_PROGRESS
        ),
        1,
    )
    stated_completed, stated_in_progress = find_stated_totals(lines)

    return Reconciliation(
        computed_completed_hours=computed_completed,
        computed_in_progress_hours=computed_in_progress,
        stated_completed_hours=stated_completed,
        stated_in_progress_hours=stated_in_progress,
    )