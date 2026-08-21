"""
Maps a validated ConversationIntent onto a concrete topic scope, and holds
the deterministic clarification copy Ask Fork sends back when it can't
confidently resolve what the student means.

Natural-language UNDERSTANDING lives in ai.interface.classify_intent()
now. Everything in this module is pure mapping and string templating over
an already-classified, already-validated intent -- no keyword matching,
and none of these strings are model-authored. The model only ever names
WHICH clarification applies (ConversationIntent.clarification_type); this
module decides what the student actually reads.
"""

from dataclasses import dataclass

from .option_intent import clarification_for_option_change

# --- scopes ----------------------------------------------------------------

BROAD = "broad"
FINANCIAL = "financial"
CAREER = "career"
TIMELINE = "timeline"
CREDITS = "credits"

ALL_SCOPES = (BROAD, FINANCIAL, CAREER, TIMELINE, CREDITS)


@dataclass
class RoutingDecision:
    scope: str | None
    clarification: str | None = None

    @property
    def needs_clarification(self) -> bool:
        return self.clarification is not None


def resolve_topic_scope(topic_scope: str, current_scope: str | None) -> RoutingDecision:
    """
    Resolve a classified topic_scope onto a concrete scope.

    "unchanged" is what replaced is_followup -- it resolves against the
    session's own prior scope. On the very first turn there's nothing to
    inherit; that's not a provider failure (the classifier answered
    correctly given what it knew), so it becomes the same deterministic
    clarification "unclear" produces, not a guess at "broad".
    """
    if topic_scope == "unchanged":
        if current_scope is None:
            return RoutingDecision(scope=None, clarification=UNCLEAR_TOPIC_MESSAGE)
        return RoutingDecision(scope=current_scope)
    if topic_scope in ALL_SCOPES:
        return RoutingDecision(scope=topic_scope)
    # "unclear", or (defensively) anything the schema shouldn't allow
    # through in the first place.
    return RoutingDecision(scope=None, clarification=UNCLEAR_TOPIC_MESSAGE)


# --- clarification copy -----------------------------------------------------

UNCLEAR_TOPIC_MESSAGE = (
    "Not sure what you'd like to look at here — cost, graduation time, "
    "credits, career outlook, or all of the tradeoffs?"
)

# Unchanged from the old keyword router's own canned message -- same
# words, new trigger (clarification_type="verdict_without_priority"
# instead of a phrase match).
VERDICT_WITHOUT_PRIORITY_MESSAGE = (
    "Fork doesn't pick a winner between majors — the dimensions "
    "aren't comparable on one scale, and which of them matters "
    "is yours to decide. What would you like to look at: cost, "
    "graduation time, credits, or career outcomes?"
)

CONFLICTING_PRIORITY_MESSAGE = (
    "It sounds like more than one thing matters here — which should "
    "Fork treat as your main priority?"
)


def ambiguous_major_message(candidates: list[str], majors: dict) -> str:
    """
    Deterministic "which did you mean" prompt for an ambiguous major
    reference (e.g. "psych" when both a B.A. and a B.S. exist). Built
    from real display names -- the same "never guess, always ask"
    principle decision_paths.change_major.major_resolution.AmbiguousMajorError
    already enforces for the manual-entry path, phrased here for a chat
    reply instead of an API error body.
    """
    names = [majors[key]["display_name"] for key in candidates if key in majors]
    if len(names) >= 2:
        if len(names) == 2:
            listed = " and ".join(names)
        else:
            listed = ", ".join(names[:-1]) + f", or {names[-1]}"
        return f"UNT offers {listed}. Which one do you mean?"
    return "Which major do you mean? Could you give the full program name?"


def clarification_message(
    clarification_type: str | None,
    *,
    majors: dict,
    ambiguous_candidates: list[str] | None = None,
    option_change_action: str | None = None,
    active_options: list[str] | None = None,
    remove_majors: list[str] | None = None,
) -> str:
    """The single place every clarification's user-facing copy comes from.

    `remove_majors` lets an unresolved REPLACE ask specifically what it's
    still missing ("which major would you like to replace X with?")
    instead of the generic add/remove phrasing -- see
    option_intent.clarification_for_option_change for why this distinction
    matters: asking "which major should I add?" about an instruction that
    was actually a replace is a real, previously-observed bug, not just an
    awkward phrasing choice.
    """
    if clarification_type == "ambiguous_major":
        return ambiguous_major_message(ambiguous_candidates or [], majors)
    if clarification_type == "ambiguous_option_change":
        return clarification_for_option_change(
            option_change_action or "add",
            active_options or [],
            remove_majors=remove_majors,
            majors_by_key=majors,
        )
    if clarification_type == "verdict_without_priority":
        return VERDICT_WITHOUT_PRIORITY_MESSAGE
    if clarification_type == "conflicting_priority":
        return CONFLICTING_PRIORITY_MESSAGE
    return UNCLEAR_TOPIC_MESSAGE
