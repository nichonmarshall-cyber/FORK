"""
One conversational turn, end to end.

This is the only place the pieces meet, and the order matters:

    student message
        |
        +-- option intent      -> WHO is compared (explicit changes only)
        +-- topic router       -> WHAT is discussed (with inheritance)
        |
    session state updated (the two independently)
        |
    deterministic engine fan-out (fresh, every turn)
        |
    authorized scoped view
        |
    AI explanation, verified against that view

The two state updates never touch each other. Narrowing the topic doesn't
narrow the options; narrowing the options doesn't change the topic. That
independence is the single most important behavior in this module, so it's
enforced structurally: the option path and the topic path never read each
other's output.

Note where the engine sits. It runs on every turn against the session's
validated inputs -- never against anything from a previous answer. Prior
AI prose is not stored, not read, and not reachable from here. The only
history this module consults is the student's own words, and only to
resolve what a vague follow-up refers to.
"""

from dataclasses import dataclass

from decision_paths.change_major.comparison import (
    MultiComparisonSnapshot,
    run_multi_comparison,
)
from decision_paths.change_major.comparison_inputs import MultiComparisonInputs

from .option_intent import (
    ACTION_CLARIFY,
    apply_option_change,
    build_major_lookup,
    detect_option_change,
)
from .router import route_question
from .session import ConversationSession
from .views import build_view


@dataclass
class TurnResult:
    """What one turn produced. Exactly one of `explanation` or
    `clarification` is set."""

    session: ConversationSession
    view: dict | None = None
    explanation: dict | None = None
    clarification: str | None = None
    used_fallback: bool = False

    @property
    def needs_clarification(self) -> bool:
        return self.clarification is not None


def ensure_snapshot(
    session: ConversationSession,
    reference_data: dict,
    force: bool = False,
) -> MultiComparisonSnapshot:
    """
    Return the session's snapshot, recomputing it if the inputs changed.

    Cached between turns because the same four pairwise runs would produce
    identical output, and fingerprinted so a corrected credit count can't
    leave a stale snapshot describing a decision that no longer exists.
    """
    if session.inputs is None:
        raise ValueError("This session has no comparison inputs yet.")

    fingerprint = session.inputs_fingerprint()

    if force or session.snapshot is None or session.snapshot_fingerprint != fingerprint:
        session.snapshot = run_multi_comparison(session.inputs, reference_data)
        session.snapshot_fingerprint = fingerprint

    return session.snapshot


def start_comparison(
    session: ConversationSession,
    inputs: MultiComparisonInputs,
    reference_data: dict,
) -> MultiComparisonSnapshot:
    """
    Set or replace the comparison a session is about.

    Resets active_options to everyone in the new inputs. Does NOT reset
    the topic scope -- a student who was asking about cost and then
    corrects their credit total is still asking about cost.
    """
    session.inputs = inputs
    session.set_active_options(inputs.all_majors())
    return ensure_snapshot(session, reference_data, force=True)


def handle_turn(
    session: ConversationSession,
    message: str,
    reference_data: dict,
    explain=None,
) -> TurnResult:
    """
    Process one student message against an established comparison.

    `explain` is injectable so the whole pipeline can be tested without an
    API key. Production passes the real AI explanation function.
    """
    if explain is None:
        from ai.interface import explain_multi_comparison

        explain = explain_multi_comparison

    if session.inputs is None:
        raise ValueError("This session has no comparison inputs yet.")

    majors = reference_data["majors"]
    lookup = build_major_lookup(majors)

    # --- WHO ------------------------------------------------------------
    # Explicit instructions only. Preference language returns ACTION_NONE
    # and the set survives untouched.
    change = detect_option_change(message, lookup, session.active_options)

    if change.action == ACTION_CLARIFY:
        # State is deliberately left exactly as it was. An ambiguous
        # instruction changes nothing until the student resolves it.
        return TurnResult(session=session, clarification=change.clarification)

    if change.changes_anything:
        session.set_active_options(
            apply_option_change(
                change,
                session.active_options,
                anchor=session.inputs.current_major,
                all_known_options=session.all_known_options(),
            )
        )

    # --- WHAT -----------------------------------------------------------
    # Reads the session's own prior scope, never the option change above.
    routing = route_question(message, session.current_topic_scope if session.turns else None)

    if routing.needs_clarification:
        session.record_turn(
            message,
            session.current_topic_scope,
            routing.intent,
            _find_referenced(message, lookup),
        )
        return TurnResult(session=session, clarification=routing.clarification)

    session.set_topic_scope(routing.scope, routing.intent)
    session.record_turn(
        message,
        routing.scope,
        routing.intent,
        _find_referenced(message, lookup),
    )

    # --- FACTS ----------------------------------------------------------
    snapshot = ensure_snapshot(session, reference_data)
    view = build_view(snapshot, session.current_topic_scope, session.active_options)

    # --- EXPLANATION ----------------------------------------------------
    result = explain(view, message)
    explanation = result["explanation"]

    return TurnResult(
        session=session,
        view=view,
        explanation=explanation.model_dump()
        if hasattr(explanation, "model_dump")
        else explanation,
        used_fallback=result.get("used_fallback", False),
    )


def _find_referenced(message: str, lookup: dict[str, str]) -> list[str]:
    """Which majors this message named, for resolving a later "the other
    two". Uses the same matcher the option-change detector does, so the
    two can't disagree about what counts as naming a major."""
    from .option_intent import _find_majors

    return _find_majors(message, lookup)
