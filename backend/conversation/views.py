"""
Builds the authorized view: the exact slice of the comparison snapshot the
model is allowed to see for one question.

Two jobs, and the second one is why this file matters more than it looks:

  1. Scope by topic. A career question gets career data. A broad question
     gets everything, because the student asked for everything — narrowing
     a broad question to save tokens would change what they asked.

  2. Be the single object the verifier's allowlist is built from. The view
     that goes into the prompt and the view that defines "which numbers
     are legitimate" are the same dict, so they cannot drift. That's what
     turns "stay on topic" from an instruction the model might ignore into
     a check that fails. A career answer reaching for a tuition figure
     fails not because a rule forbade it, but because that number was
     never in the authorized view.

Scoping by options happens here too, and independently: the view contains
whichever majors are in active_options, at whatever topic scope was
routed. Narrowing the topic never drops an option, and narrowing the
options never changes the topic.
"""

from decision_paths.change_major.comparison import (
    STATUS_CALCULATED,
    MultiComparisonSnapshot,
)

from .router import BROAD, CAREER, CREDITS, FINANCIAL, TIMELINE

# Which dimension blocks each scope authorizes. These follow the real
# dependencies in the data rather than tidy categories: a financial answer
# needs the timeline figures because extra semesters are what drive the
# extra cost, and a timeline answer needs credits because unapplied
# credits are what drive extra semesters. Leaving those out would produce
# answers that state a number and can't explain it.
#
# "earnings" (salary figures + Career/Salary Outlook trajectory) and
# "career" (occupations/Job Market Demand only) are deliberately separate
# blocks -- see _dimensions_from_result() in comparison.py. FINANCIAL is
# authorized for "earnings" specifically (permitted early-career context)
# without gaining Job Market Demand/occupation data, which stays
# CAREER-exclusive.
_SCOPE_BLOCKS: dict[str, tuple[str, ...]] = {
    BROAD: ("financial", "timeline", "credits", "earnings", "career", "program"),
    FINANCIAL: ("financial", "timeline", "credits", "earnings"),
    CAREER: ("earnings", "career"),
    TIMELINE: ("timeline", "credits"),
    CREDITS: ("credits", "timeline", "program"),
}


def build_view(
    snapshot: MultiComparisonSnapshot,
    scope: str,
    active_options: list[str],
    stated_priority: str | None = None,
) -> dict:
    """
    The authorized view for one turn.

    `active_options` includes the anchor. Options in the snapshot that
    aren't currently active are left out entirely — not marked inactive,
    left out — so there's no path by which a number belonging to a major
    the student removed can be quoted back at them.

    Pending and failed options stay in the view when they're active. The
    model needs to know Mechanical Engineering is missing a figure so it
    can say so; it just gets no numbers for it, which means it can't
    invent any either.
    """
    blocks = _SCOPE_BLOCKS.get(scope, _SCOPE_BLOCKS[BROAD])

    options_view = []
    for outcome in snapshot.outcomes:
        if outcome.major_key not in active_options:
            continue

        entry = {
            "major": outcome.major_display,
            "status": outcome.status,
        }
        if outcome.status == STATUS_CALCULATED and outcome.dimensions:
            entry["data"] = {
                name: outcome.dimensions[name]
                for name in blocks
                if name in outcome.dimensions
            }
        if outcome.missing_fields:
            entry["missing_fields"] = outcome.missing_fields
        if outcome.error:
            entry["error"] = outcome.error
        options_view.append(entry)

    return {
        "topic_scope": scope,
        "current_major": snapshot.anchor_display,
        "credits_completed": snapshot.credits_completed,
        "options": options_view,
        # Assumptions and limitations always travel with the view. They're
        # what keeps an explanation honest about what the numbers can't
        # prove, and dropping them on a narrow question would produce a
        # confident answer with its caveats stripped off.
        "assumptions": snapshot.assumptions,
        "limitations": snapshot.limitations,
        # Only ever set when the student explicitly stated it (see
        # ConversationSession.stated_priority) -- lets the explanation
        # anchor a verdict-shaped answer to a priority the student actually
        # gave, without Fork inventing one or ranking dimensions itself.
        "stated_priority": stated_priority,
    }


def view_has_any_data(view: dict) -> bool:
    """True when at least one active option actually has numbers. A view
    where every option is pending can still be explained — "here's what
    I still need from you" — but it shouldn't be sent through the normal
    comparison prompt as though there were something to compare."""
    return any("data" in option for option in view.get("options", []))
