"""
Deciding what a set of academic documents establishes.

Pure functions. Nothing here imports FastAPI, touches a session, or builds a
response — every rule below is exercisable by constructing a
StudentAcademicRecord and calling a function. That matters because these are
the rules that decide which numbers a student sees, and rules embedded in a
route handler can only be tested through HTTP.

The central distinction, and the one easiest to get wrong:

    completed hours   -- what the student has earned, full stop
    applicable hours  -- what counts toward one specific degree

A current audit establishes the first. A What-If audit establishes the second,
*for the program it was run against and no other*. They are different measures,
so a gap between them is ordinary non-transferable credit rather than a
contradiction, and nothing here reports one as a conflict.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DocumentRole(str, Enum):
    CURRENT_AUDIT = "current_audit"
    WHAT_IF_AUDIT = "what_if_audit"
    TRANSCRIPT = "transcript"
    UNSUPPORTED = "unsupported"


class MatchQuality(str, Enum):
    EXACT = "exact"
    """The program code resolved to exactly one known major."""

    AMBIGUOUS = "ambiguous"
    """Zero or several. The document is held for review and supplies nothing.
    There is no near-match fallback: guessing which degree a student is
    considering is precisely the guess that produces a confident wrong
    number."""


class ProgramMatch(BaseModel):
    quality: MatchQuality
    program_key: str | None = None
    candidates: list[str] = Field(default_factory=list)
    reason: str | None = None


class DocumentClassification(BaseModel):
    role: DocumentRole
    program_name: str | None = None
    program_code: str | None = None
    catalog_year: str | None = None
    prepared_at: str | None = None
    match: ProgramMatch | None = None

    @property
    def supplies_option_credits(self) -> bool:
        return (
            self.role == DocumentRole.WHAT_IF_AUDIT
            and self.match is not None
            and self.match.quality == MatchQuality.EXACT
        )


class DiscrepancyCode(str, Enum):
    DOCUMENT_DATE_GAP = "document_date_gap"
    SHARED_FACT_CONTRADICTION = "shared_fact_contradiction"


class Discrepancy(BaseModel):
    code: DiscrepancyCode
    user_message: str
    technical_detail: str
    magnitude: str


#: One academic term. Within a term coursework is unlikely to have changed;
#: across one, grades have posted and a degree audit run before it may
#: predate work the student has since finished.
DOCUMENT_DATE_GAP_DAYS = 90


def classify_document(record, majors: dict[str, dict]) -> DocumentClassification:
    """Work out what a parsed document is and which program it speaks for.

    Role comes from the parser's own `is_what_if`, which reads UNT's
    not-finalized banner. Nothing is inferred from the program name.
    """
    role = (
        DocumentRole.WHAT_IF_AUDIT
        if getattr(record, "is_what_if", False)
        else DocumentRole.CURRENT_AUDIT
    )

    return DocumentClassification(
        role=role,
        program_name=record.program,
        program_code=record.program_code,
        catalog_year=record.catalog_year,
        prepared_at=record.audit_prepared_at,
        match=resolve_program_key(record, majors),
    )


def resolve_program_key(record, majors: dict[str, dict]) -> ProgramMatch:
    """Map a document's program onto exactly one known major key, or refuse.

    Matching is on normalized display and official program names. A code like
    `ENBS CSCI` is UNT's internal identifier and is not currently mapped, so
    the name is what carries the match.

    Refusing on ambiguity is deliberate. A Psychology document that resolved
    to both psychology_ba and psychology_bs must supply neither — picking one
    would attach a B.A.'s applicable hours to a B.S. comparison and report it
    as document-derived.
    """
    name = (record.program or "").strip()
    if not name:
        return ProgramMatch(
            quality=MatchQuality.AMBIGUOUS,
            reason="The document does not state a program name.",
        )

    normalized = _normalize(name)
    hits = [
        key
        for key, entry in majors.items()
        if _normalize(entry.get("display_name", "")) in normalized
        or _normalize(entry.get("official_program_name", "")) in normalized
    ]

    # A B.A./B.S. pair both match on the shared subject name. The degree type
    # in the document's own title is what separates them.
    if len(hits) > 1:
        by_degree = [
            key
            for key in hits
            if _degree_matches(name, majors[key].get("degree_type", ""))
        ]
        if len(by_degree) == 1:
            hits = by_degree

    if len(hits) == 1:
        return ProgramMatch(quality=MatchQuality.EXACT, program_key=hits[0])

    return ProgramMatch(
        quality=MatchQuality.AMBIGUOUS,
        candidates=sorted(hits),
        reason=(
            f"'{name}' matches {len(hits)} known programs."
            if hits
            else f"'{name}' does not match a program Fork knows about."
        ),
    )


def _normalize(value: str) -> str:
    return " ".join(value.lower().replace(".", "").split())


def _degree_matches(program_name: str, degree_type: str) -> bool:
    """Whether a document title carries a specific degree type.

    'Bachelor of Science in Psychology' vs a B.A. entry. Compared with dots
    stripped so 'B.S.' and 'BS' agree.
    """
    if not degree_type:
        return False
    compact = _normalize(degree_type)
    spelled = {"bs": "bachelor of science", "ba": "bachelor of arts"}.get(compact)
    normalized_name = _normalize(program_name)
    return compact in normalized_name.split() or (
        spelled is not None and spelled in normalized_name
    )


def detect_discrepancies(current_record, what_if_record) -> list[Discrepancy]:
    """Find genuine disagreements between two confirmed documents.

    Exactly two rules, both defined in terms of comparable quantities.

    What is deliberately NOT a discrepancy: a current audit reporting 81
    completed hours alongside a What-If reporting 66 applicable hours. Those
    measure different things, and the 15-hour gap is ordinary
    non-transferable credit. Reporting it as a conflict would teach students
    to distrust output that was correct.
    """
    if current_record is None or what_if_record is None:
        return []

    found: list[Discrepancy] = []

    gap = _days_between(current_record.audit_prepared_at, what_if_record.audit_prepared_at)
    dates_are_far_apart = gap is not None and gap > DOCUMENT_DATE_GAP_DAYS

    if dates_are_far_apart:
        # Bound to a local so the narrowing survives into the f-strings below.
        # `gap` is Optional by declaration and only non-None inside this
        # branch, which the reader can see but a type checker cannot infer
        # through a separately-computed boolean.
        days = gap or 0
        found.append(
            Discrepancy(
                code=DiscrepancyCode.DOCUMENT_DATE_GAP,
                magnitude=f"{days} days",
                technical_detail=(
                    f"prepared_at differs by {days} days, over the "
                    f"{DOCUMENT_DATE_GAP_DAYS}-day threshold "
                    f"({current_record.audit_prepared_at} vs "
                    f"{what_if_record.audit_prepared_at})."
                ),
                user_message=(
                    "These two documents were prepared about "
                    f"{days // 30} months apart "
                    f"({current_record.audit_prepared_at} and "
                    f"{what_if_record.audit_prepared_at}). The older one may "
                    "not include coursework you've finished since. Check that "
                    "both still describe where you are now."
                ),
            )
        )

    # Same measure, same student, two answers -- but only worth reporting
    # when the dates DON'T already account for it. Documents prepared five
    # months apart are supposed to disagree about completed hours; saying so
    # twice turns one explicable difference into two alarms and trains the
    # student to dismiss both. An unexplained difference between documents
    # from the same week is the genuinely suspicious case.
    if dates_are_far_apart:
        return found

    for label, attribute in (
        ("completed", "completed_hours"),
        ("in-progress", "in_progress_hours"),
    ):
        mine = getattr(current_record, attribute, None)
        theirs = getattr(what_if_record, attribute, None)
        if mine is None or theirs is None or mine == theirs:
            continue
        found.append(
            Discrepancy(
                code=DiscrepancyCode.SHARED_FACT_CONTRADICTION,
                magnitude=f"{abs(mine - theirs):g} hours",
                technical_detail=(
                    f"{attribute}: current audit states {mine:g}, "
                    f"what-if states {theirs:g}."
                ),
                user_message=(
                    f"Your two documents report different {label} hours "
                    f"({mine:g} and {theirs:g}). Fork uses the figure from "
                    "your current degree audit."
                ),
            )
        )

    return found


#: The audit block stating progress toward the degree as a whole.
_TOTAL_HOURS_BLOCK = "TOTAL HOURS"


def degree_applicable_hours(record) -> float | None:
    """Hours the audit says apply to ITS degree, not hours the student has.

    These are different numbers and the difference is the whole point of a
    What-If. Summing the course list gives what the student has earned
    anywhere; the degree's TOTAL HOURS block gives what counts toward this
    program. They coincide when everything transfers and diverge otherwise,
    which is exactly the case a student runs a What-If to discover.

    Returns None when the block is absent, because an unknown applicable
    figure must not silently fall back to the completed total -- that
    substitution would assume everything transfers and report it as
    document-derived.
    """
    for requirement in getattr(record, "requirements", []):
        if _TOTAL_HOURS_BLOCK in requirement.title.upper():
            return requirement.hours_earned
    return None


def _days_between(a: str | None, b: str | None) -> int | None:
    first, second = _parse_prepared(a), _parse_prepared(b)
    if first is None or second is None:
        return None
    return abs((first - second).days)


def _parse_prepared(value: str | None) -> datetime | None:
    """UNT prints '08/18/2026 03:18 PM'. Returns None rather than raising —
    an unreadable date means the gap can't be checked, which is different
    from there being no gap and must not be reported as agreement."""
    if not value:
        return None
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


class ResolvedOptionCredits(BaseModel):
    """What a confirmed What-If contributes to one comparison option."""

    program_key: str
    credits_transferable: int
    source: str
    source_date: str


class ResolvedInputs(BaseModel):
    """Everything the confirmed collection establishes.

    Deliberately partial, and deliberately NOT a MultiComparisonInputs. The
    audit session and the conversation session are separate stores with no
    link between them, so nothing here may assign comparison inputs. This is
    handed to the frontend, which applies it to the form; the student then
    calculates, and that calculation is what Ask Fork grounds on.
    """

    credits_completed: int | None = None
    credits_in_progress: int | None = None
    credits_source: str | None = None
    credits_source_date: str | None = None
    option_credits: ResolvedOptionCredits | None = None
    manual_restore: dict[str, int] = Field(default_factory=dict)
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    requires_acknowledgement: bool = False
    unresolved: list[str] = Field(default_factory=list)


def resolve_comparison_inputs(
    current_record,
    what_if_record,
    what_if_classification: DocumentClassification | None,
    manual_transferable_by_major: dict[str, int],
    acknowledged: bool,
) -> ResolvedInputs:
    """Decide what the confirmed documents supply, and to which option.

    The single writer. Every ownership rule lives here, so there is exactly
    one place that can violate them:

        current audit  -> completed and in-progress hours, shared
        what-if        -> credits_transferable for its matched option ONLY
        manual         -> every other option, untouched

    Callers pass already-confirmed records; an unconfirmed or freshly
    corrected document should never reach this function.
    """
    resolved = ResolvedInputs(manual_restore=dict(manual_transferable_by_major))

    if current_record is not None:
        resolved.credits_completed = round(current_record.completed_hours)
        resolved.credits_in_progress = round(current_record.in_progress_hours)
        resolved.credits_source = "UNT Degree Audit, confirmed by you"
        resolved.credits_source_date = current_record.audit_prepared_at or "Not stated"

    resolved.discrepancies = detect_discrepancies(current_record, what_if_record)
    resolved.requires_acknowledgement = bool(resolved.discrepancies) and not acknowledged

    if what_if_record is None or what_if_classification is None:
        return resolved

    if not what_if_classification.supplies_option_credits:
        match = what_if_classification.match
        resolved.unresolved.append(
            match.reason if match and match.reason else "Program could not be identified."
        )
        return resolved

    # An unacknowledged disagreement blocks the document-derived figure but
    # leaves shared facts alone: the student can still see what their current
    # audit says while deciding about the conflict.
    if resolved.requires_acknowledgement:
        resolved.unresolved.append(
            "Waiting for you to confirm how these documents should be read together."
        )
        return resolved

    applicable = degree_applicable_hours(what_if_record)
    if applicable is None:
        # No substituting the completed total here -- see
        # degree_applicable_hours. Better to keep the manual estimate than to
        # present an assumption as a document-derived figure.
        resolved.unresolved.append(
            "This What-If audit doesn't state how many hours apply to the "
            "degree overall, so Fork can't use it for that figure yet."
        )
        return resolved

    resolved.option_credits = ResolvedOptionCredits(
        program_key=what_if_classification.match.program_key,  # type: ignore[union-attr]
        credits_transferable=round(applicable),
        source=(
            f"UNT What-If Audit — {what_if_classification.program_name}"
            f"{f', {what_if_classification.catalog_year}' if what_if_classification.catalog_year else ''}"
            ", confirmed by you"
        ),
        source_date=what_if_record.audit_prepared_at or "Not stated",
    )
    return resolved


def evidence_fingerprint(
    current_record,
    current_revision: int,
    what_if_record,
    what_if_revision: int,
    what_if_classification: DocumentClassification | None,
    discrepancies: list[Discrepancy],
) -> str:
    """Identify exactly the evidence an acknowledgement was given for.

    Permission attaches to a specific set of facts and evaporates when they
    change. The revision counters are what make a correction invalidate an
    acknowledgement even when the totals happen to land back on the same
    number — the student agreed to proceed given documents they were shown,
    and an edited document is not one of them.
    """
    parts: list[str] = []
    for record, revision, label in (
        (current_record, current_revision, "current"),
        (what_if_record, what_if_revision, "whatif"),
    ):
        if record is None:
            parts.append(f"{label}:none")
            continue
        parts.append(
            f"{label}:{record.audit_prepared_at}:{revision}:"
            f"{record.completed_hours:g}:{record.in_progress_hours:g}"
        )

    if what_if_classification and what_if_classification.match:
        parts.append(f"program:{what_if_classification.match.program_key}")
    else:
        parts.append("program:none")

    for d in sorted(discrepancies, key=lambda x: (x.code.value, x.magnitude)):
        parts.append(f"{d.code.value}:{d.magnitude}")

    return "|".join(parts)