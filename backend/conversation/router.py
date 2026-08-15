"""
Decides WHAT the student is asking about. Never decides WHO is being
compared — that's the session's active_options, and the two must not
influence each other.

The rule that makes this feel like a conversation rather than a form: a
follow-up with no topic words in it inherits the topic you were already
on. "Which one costs more?" then "okay, what's working against me?" stays
financial. Resetting to a broad answer there would make the student repeat
"financially" in every message, which is exactly the robot behavior this
is meant to avoid.

Priority ladder, in order:

  1. Explicit topic signal            -> switch to that scope
  2. Conversational follow-up, no
     topic signal, prior scope exists -> INHERIT the prior scope
  3. No usable prior context          -> BROAD
  4. Genuinely ambiguous              -> ask, change nothing

Broad markers ("what are the tradeoffs", "compare these") count as an
explicit signal, resolved in the same pass as the other five. Otherwise
asking to widen the comparison right after a cost question would inherit
financial and quietly refuse to widen.

Keyword matching, deliberately. It's deterministic, it's testable without
a model, and a routing decision that can hallucinate is a routing decision
that can silently send the wrong data to the explanation layer.
"""

from dataclasses import dataclass

# --- scopes --------------------------------------------------------------

BROAD = "broad"
FINANCIAL = "financial"
CAREER = "career"
TIMELINE = "timeline"
CREDITS = "credits"

ALL_SCOPES = (BROAD, FINANCIAL, CAREER, TIMELINE, CREDITS)

# How the router arrived at a scope. Stored on the session as
# last_question_intent, and useful in tests and logs for telling "the
# student asked about cost" apart from "the student said something vague
# and we kept the previous topic".
INTENT_EXPLICIT = "explicit"
INTENT_INHERITED = "inherited"
INTENT_DEFAULT_BROAD = "default_broad"
INTENT_AMBIGUOUS = "ambiguous"


@dataclass
class RoutingDecision:
    scope: str | None
    intent: str
    clarification: str | None = None

    @property
    def needs_clarification(self) -> bool:
        return self.intent == INTENT_AMBIGUOUS


# --- keyword tables ------------------------------------------------------
#
# Checked in this order, first match wins. Ordering matters where a
# question could plausibly hit two tables: "how long until I graduate"
# contains both a timeline word and, in some phrasings, a cost word, and
# timeline is the better read of it.

_BROAD_MARKERS = (
    "compare these", "compare all", "compare them", "compare the",
    "tradeoff", "trade-off", "trade off",
    "biggest difference", "what's different", "whats different",
    "what is different", "overall", "big picture", "everything",
    "what should i know", "walk me through", "full comparison",
    "all of them", "across the board", "in general", "summarize",
    "summarise", "give me the rundown", "rundown",
)

_TOPIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        TIMELINE,
        (
            "graduat", "how long", "longer", "sooner", "faster", "quicker",
            "semester", "timeline", "time to finish", "finish faster",
            "delay", "behind", "on time", "extra time", "when will i",
            "how many terms", "term",
        ),
    ),
    (
        FINANCIAL,
        (
            "cost", "costs", "cheaper", "expensive", "afford", "tuition",
            "money", "price", "pay for", "financial", "debt", "loan",
            "spend", "budget", "worth paying", "dollar", "how much",
        ),
    ),
    (
        CAREER,
        (
            "career", "job", "jobs", "salary", "salaries", "earn", "earning",
            "income", "pay after", "wage", "occupation", "outlook",
            "employment", "hiring", "demand", "industry", "work in",
            "make more", "market",
        ),
    ),
    (
        CREDITS,
        (
            "credit", "credits", "transfer", "apply toward", "applies",
            "coursework", "classes count", "courses count", "requirement",
            "prereq", "prerequisite", "degree plan", "audit", "lose credit",
        ),
    ),
)

# Phrases that clearly continue the previous topic without naming it.
# These are what let inheritance fire instead of the broad default.
_FOLLOWUP_MARKERS = (
    "what about", "how about", "what's working", "whats working",
    "working against", "working for", "and the", "what else", "anything else",
    "why is that", "why's that", "how so", "tell me more", "more on that",
    "go deeper", "expand on", "elaborate", "which one", "which ones",
    "is that", "does that", "so then", "okay so", "ok so", "and that",
    "the downside", "the upside", "the catch", "what's the catch",
)

# Questions too vague to route even with prior context. Only fires when
# nothing else matched — a bare "what about the other two?" is an option
# question, not a topic one, and gets handled before this.
#
# Note these are checked AFTER the topic tables, which is what keeps
# "which one is cheaper?" a financial question rather than a verdict
# request — it has a cost word in it, so it never reaches here.
_AMBIGUOUS_MARKERS = (
    "what do you think", "what should i do", "help me decide",
    "is better", "are better", "is best", "are best",
    "better option", "better choice", "better major", "better path",
    "best option", "best choice", "best major", "best path",
    "should i pick", "should i choose", "should i go with",
    "what's best", "whats best", "what would you", "your opinion",
    "recommend", "which one wins", "which wins",
)


def _contains_any(text: str, needles) -> bool:
    return any(n in text for n in needles)


def route_question(
    question: str,
    current_scope: str | None = None,
) -> RoutingDecision:
    """
    Resolve one question to a topic scope.

    `current_scope` is the session's current_topic_scope, or None on the
    first turn of a conversation.
    """
    text = question.lower().strip()

    if not text:
        return RoutingDecision(scope=current_scope or BROAD, intent=INTENT_DEFAULT_BROAD)

    # 1a. Explicit request to widen. Checked before the topic tables so
    # "what are the tradeoffs" after a cost question widens instead of
    # inheriting financial.
    if _contains_any(text, _BROAD_MARKERS):
        return RoutingDecision(scope=BROAD, intent=INTENT_EXPLICIT)

    # 1b. Explicit topic.
    for scope, keywords in _TOPIC_KEYWORDS:
        if _contains_any(text, keywords):
            return RoutingDecision(scope=scope, intent=INTENT_EXPLICIT)

    # 4. Vague enough that guessing would be worse than asking. Note this
    # sits ABOVE inheritance: "which is better?" isn't a follow-up about
    # the current topic, it's a request for a verdict Fork doesn't give.
    if _contains_any(text, _AMBIGUOUS_MARKERS):
        return RoutingDecision(
            scope=None,
            intent=INTENT_AMBIGUOUS,
            clarification=(
                "Fork doesn't pick a winner between majors — the dimensions "
                "aren't comparable on one scale, and which of them matters "
                "is yours to decide. What would you like to look at: cost, "
                "graduation time, credits, or career outcomes?"
            ),
        )

    # 2. Follow-up with no topic words: stay where we are.
    if current_scope and _contains_any(text, _FOLLOWUP_MARKERS):
        return RoutingDecision(scope=current_scope, intent=INTENT_INHERITED)

    # 2b. Short pronoun-ish continuations ("and Mechanical?", "the other
    # two?") carry no topic words at all. If we're already on a topic,
    # continuing it beats resetting.
    if current_scope and len(text.split()) <= 6:
        return RoutingDecision(scope=current_scope, intent=INTENT_INHERITED)

    # 3. Nothing to inherit, nothing explicit.
    return RoutingDecision(scope=BROAD, intent=INTENT_DEFAULT_BROAD)
