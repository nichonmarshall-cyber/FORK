"""
One conversational turn, end to end.

This is the only place the pieces meet, and the order matters:

    student message
        |
        +-- pending numeric reply?  -> resolved deterministically, no AI call
        |
        +-- intent classification   -> WHAT the student means (closed, validated)
        |
    session state updated (WHO, WHAT, and priority -- independently)
        |
    deterministic engine fan-out (fresh, every turn)
        |
    authorized scoped view
        |
    AI explanation, verified against that view
        |
    deterministic navigation (pills / auto-focus), never model-authored

The three state updates never touch each other. Narrowing the topic
doesn't narrow the options; narrowing the options doesn't change the
topic; neither touches a stated priority. That independence is the single
most important behavior in this module, so it's enforced structurally:
each path writes exactly one thing and never reads another path's output.

Note where the engine sits. It runs on every turn against the session's
validated inputs -- never against anything from a previous answer. Prior
AI prose is not stored, not read, and not reachable from here. The only
history this module consults is the student's own words, and only to
resolve what a vague follow-up refers to.
"""

import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from decision_paths.change_major.comparison import (
    STATUS_CALCULATED,
    MultiComparisonSnapshot,
    run_multi_comparison,
)
from decision_paths.change_major.comparison_inputs import (
    ComparisonOption,
    MultiComparisonInputs,
)

from .option_intent import (
    ACTION_ADD,
    ACTION_CLARIFY,
    ACTION_REMOVE,
    ACTION_REPLACE,
    ACTION_RESTORE_ALL,
    apply_option_change,
    intent_to_option_change,
)
from .router import clarification_message, resolve_topic_scope
from .session import (
    ConversationSession,
    PendingAnalysisQuestion,
    PendingFieldRequest,
    PendingOptionAction,
)
from .views import build_view

# A reply that's cleanly "just a number" resolving a pending field request
# -- "61", "61 credits", "about 61 credits apply". This is the
# deterministic fast path: no ambiguity to interpret, so it's handled
# without an AI call. It also already matches most natural-language
# replies with exactly one digit run ("I think 61 apply"). Anything with
# more than one number, or no digit at all (spelled out, or a reply that
# isn't an answer at all), falls through to intent classification, which
# gets pending_field_request as context and can resolve it via
# ConversationIntent.pending_field_value -- or determine the student
# changed the subject, in which case the pending state is discarded. See
# handle_turn()'s pending-field handling for the full sequence.
_BARE_NUMBER_RE = re.compile(r"^\D*(\d+)\D*$")

# clarification_types that are about the ANALYSIS question, never about
# resolving who's being compared -- these must never block an otherwise
# fully-resolved mutation from applying. ambiguous_major/
# ambiguous_option_change are deliberately absent: those ARE about
# resolving WHO, so they keep blocking the mutation exactly as before.
_ANALYSIS_ONLY_CLARIFICATIONS = frozenset(
    {"verdict_without_priority", "unclear_topic", "conflicting_priority"}
)


@dataclass
class TurnResult:
    """What one turn produced. Exactly one of `explanation` or
    `clarification` is set, unless `ai_unavailable` is True, in which case
    neither is -- see the module docstring on failure handling."""

    session: ConversationSession
    view: dict | None = None
    explanation: dict | None = None
    clarification: str | None = None
    used_fallback: bool = False
    ai_unavailable: bool = False
    navigation_pills: list[dict] = field(default_factory=list)
    navigation_target: dict | None = None

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

    Cached between turns because the same pairwise runs would produce
    identical output, and fingerprinted so a corrected credit count -- or
    a chat-driven option addition -- can't leave a stale snapshot
    describing a decision that no longer exists.
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
    the topic scope or stated priority -- a student who was asking about
    cost and cares most about graduating quickly is still asking about
    cost and still cares about that, even after correcting a credit total.
    """
    session.set_inputs(inputs)
    session.set_active_options(inputs.all_majors())
    return ensure_snapshot(session, reference_data, force=True)


def handle_turn(
    session: ConversationSession,
    message: str,
    reference_data: dict,
    selected_detail_path: str | None = None,
    available_nodes: list[dict] | None = None,
    classify=None,
    explain=None,
) -> TurnResult:
    """
    Process one student message against an established Compare Multiple
    comparison.

    `classify`/`explain` are injectable so the whole pipeline can be
    tested without an API key. Production passes the real intent
    classifier and explanation function.

    `selected_detail_path` is a per-request hint from the frontend (which
    alternative's map is currently displayed) -- never persisted on the
    session, exactly like `selected_node_id` already reaches /explain
    today. It only affects navigation (see _compute_navigation), never
    active_options or topic scope.
    """
    if classify is None:
        from ai.interface import classify_intent

        classify = classify_intent
    if explain is None:
        from ai.interface import explain_multi_comparison

        def explain(view, question, available_nodes=None):
            return explain_multi_comparison(view, question, available_nodes=available_nodes)

    if session.inputs is None:
        raise ValueError("This session has no comparison inputs yet.")

    majors = reference_data["majors"]
    valid_majors = {key: entry["display_name"] for key, entry in majors.items()}

    # --- pending field: bare-number fast path, no AI call ----------------
    if session.pending_field_request is not None:
        match = _BARE_NUMBER_RE.match(message.strip())
        if match:
            resolved = _resolve_pending_field(
                session,
                int(match.group(1)),
                reference_data,
                explain=explain,
                available_nodes=available_nodes,
                selected_detail_path=selected_detail_path,
            )
            if resolved is not None:
                return resolved
            # _resolve_pending_field only returns None when the pending
            # option is genuinely gone (already cleared internally in
            # that case) -- an invalid VALUE returns a real clarification
            # TurnResult above, not None. Falling through here only
            # happens for the "option's gone" case, so classification
            # below proceeds with a clean slate.

    # --- WHAT THE STUDENT MEANS -----------------------------------------
    intent = classify(
        message,
        valid_majors,
        current_topic_scope=session.current_topic_scope if session.turns else None,
        active_options=session.active_options,
        stated_priority=session.stated_priority,
        selected_detail_path=selected_detail_path,
        pending_option_action=_pending_option_action_context(session),
        known_option_credits=_known_option_credits(session),
        pending_field_request=_pending_field_request_context(session),
    )

    if intent is None:
        # Provider/parse/schema failure after retry. Never guess, never
        # fall back to keyword matching (there is none), never touch
        # state. See TurnResult.ai_unavailable.
        return TurnResult(session=session, ai_unavailable=True)

    # --- pending field: natural-language resolution or release -----------
    # A message that didn't match the bare-number fast path still might
    # answer the pending field ("86 credits apply", "I think 86 apply")
    # -- the classifier gets a real chance to recognize that before
    # pending state is discarded. Only a message the classifier
    # determines does NOT answer it (a genuine subject change, e.g. "what
    # does salary look like instead?") releases the pending state.
    if session.pending_field_request is not None:
        if intent.pending_field_value is not None:
            resolved = _resolve_pending_field(
                session,
                intent.pending_field_value,
                reference_data,
                explain=explain,
                available_nodes=available_nodes,
                selected_detail_path=selected_detail_path,
            )
            if resolved is not None:
                return resolved
        else:
            session.pending_field_request = None
            session.pending_analysis_question = None

    # --- clarification -----------------------------------------------------
    # Only ambiguous_major/ambiguous_option_change are about resolving WHO
    # is being compared -- those block the mutation exactly as before.
    # Everything else (verdict_without_priority, unclear_topic,
    # conflicting_priority) is about the ANALYSIS question and must never
    # discard an otherwise fully-resolved mutation in the same message.
    analysis_clarification: str | None = None
    if intent.needs_clarification:
        remove_majors = list(intent.remove_options)
        if intent.clarification_type not in _ANALYSIS_ONLY_CLARIFICATIONS:
            if intent.clarification_type == "ambiguous_option_change":
                # Preserve whatever WAS understood about the instruction
                # -- e.g. "replace Psych BA" with no target major named
                # still tells us the action was a replace and which
                # major is leaving, so a follow-up naming only the new
                # major (or a repeated clarification) asks about the
                # right thing instead of defaulting to "which major
                # should I add?".
                session.pending_option_action = PendingOptionAction(
                    action=intent.option_change,
                    remove_majors=remove_majors,
                    add_majors=[o.major for o in intent.add_options],
                )
            text = clarification_message(
                intent.clarification_type,
                majors=majors,
                ambiguous_candidates=intent.ambiguous_candidates,
                option_change_action=intent.option_change,
                active_options=session.active_options,
                remove_majors=remove_majors,
            )
            session.record_turn(
                message, session.current_topic_scope, "clarification", intent.referenced_majors
            )
            return TurnResult(session=session, clarification=text)
        # Analysis-only: remember the clarification text, but keep going
        # -- a clear mutation in this same message still applies below.
        analysis_clarification = clarification_message(
            intent.clarification_type,
            majors=majors,
            ambiguous_candidates=intent.ambiguous_candidates,
            option_change_action=intent.option_change,
            active_options=session.active_options,
            remove_majors=remove_majors,
        )

    # --- PRIORITY --------------------------------------------------------
    # Independent of everything else here -- only ever written from an
    # explicit ConversationIntent.priority_update.
    session.apply_priority_update(intent.priority_update)

    # --- WHO ---------------------------------------------------------------
    change = intent_to_option_change(intent)
    pending_ask = _apply_option_change(session, intent, change, majors)
    if isinstance(pending_ask, TurnResult):
        # A validation failure (e.g. MAX_OPTIONS exceeded) -- state was
        # never mutated, so this is safe to return immediately. Takes
        # priority over any analysis-only clarification: a rejected
        # mutation needs the student's attention before anything else.
        return pending_ask

    # An analysis-only clarification (see above) replaces the rest of
    # this turn's normal processing -- the mutation above already
    # applied, if there was one, so the response confirms it alongside
    # asking what the analysis question needs.
    if analysis_clarification is not None:
        confirmation = _mutation_confirmation(change, intent, majors) if change.changes_anything else None
        text = f"{confirmation} {analysis_clarification}" if confirmation else analysis_clarification
        session.record_turn(
            message, session.current_topic_scope, "clarification", intent.referenced_majors
        )
        return TurnResult(session=session, clarification=text)

    # --- WHAT --------------------------------------------------------------
    # Reads the session's own prior scope, never the option change above.
    routing = resolve_topic_scope(
        intent.topic_scope, session.current_topic_scope if session.turns else None
    )
    if routing.needs_clarification:
        session.record_turn(
            message, session.current_topic_scope, "clarification", intent.referenced_majors
        )
        return TurnResult(session=session, clarification=routing.clarification)

    session.set_topic_scope(
        routing.scope, "inherited" if intent.topic_scope == "unchanged" else "explicit"
    )
    session.record_turn(
        message, session.current_topic_scope, "explicit", intent.referenced_majors
    )

    # A conversational add that left exactly one required field missing
    # gets an explicit, deterministic ask THIS turn rather than a passive
    # mention folded into a broader answer -- short-circuits before the
    # explanation model is ever called.
    if pending_ask is not None:
        major_display = majors[pending_ask]["display_name"]
        session.pending_field_request = PendingFieldRequest(
            major=pending_ask, field="credits_transferable"
        )
        # Only remember a resumable analysis question when THIS message
        # actually stated a fresh topic ("unchanged" means nothing was
        # said about topic at all, e.g. a bare "Add X" -- nothing to
        # resume there).
        if intent.topic_scope != "unchanged":
            session.pending_analysis_question = PendingAnalysisQuestion(
                topic_scope=session.current_topic_scope, original_message=message
            )
        text = (
            f"{major_display} has been added. How many of your "
            f"{session.inputs.credits_completed} completed credits apply to it?"
        )
        # Force a rebuild so the newly-added (pending) option is reflected
        # in the snapshot the response carries back -- the FACTS step
        # below is skipped on this short-circuit path, so nothing else
        # would refresh it.
        ensure_snapshot(session, reference_data, force=True)
        return TurnResult(session=session, explanation=_ask_as_explanation(text))

    # --- FACTS -------------------------------------------------------------
    snapshot = ensure_snapshot(session, reference_data)
    view = build_view(
        snapshot, session.current_topic_scope, session.active_options, session.stated_priority
    )

    # --- EXPLANATION ---------------------------------------------------------
    result = explain(view, message, available_nodes=available_nodes)
    explanation = result["explanation"]
    explanation_dict = (
        explanation.model_dump() if hasattr(explanation, "model_dump") else explanation
    )

    related_node_ids = explanation_dict.get("related_node_ids", [])
    pills, target = _compute_navigation(
        related_node_ids,
        intent.referenced_majors,
        session.active_options,
        snapshot,
        selected_detail_path,
    )

    return TurnResult(
        session=session,
        view=view,
        explanation=explanation_dict,
        used_fallback=result.get("used_fallback", False),
        navigation_pills=pills,
        navigation_target=target,
    )


def _ask_as_explanation(text: str) -> dict:
    """Wraps a deterministic ask/confirmation in the same DecisionExplanation
    shape every other answer takes, so main.py and the frontend never have
    to special-case this response's structure -- only its content is
    different from a normal explanation."""
    return {
        "direct_answer": text,
        "key_points": [],
        "limitations": [],
        "still_useful_for": [],
        "next_step": None,
        "related_node_ids": [],
    }


def _mutation_confirmation(change, intent, majors: dict) -> str | None:
    """
    A short, deterministic sentence describing what an option-change
    instruction just did. Used only when an analysis-only clarification
    (see _ANALYSIS_ONLY_CLARIFICATIONS) is about to take the place of
    this turn's explanation, so a student who said "replace X with Y,
    then tell me which is best overall" sees that the replace actually
    happened before Fork asks what "best overall" should mean -- rather
    than the mutation succeeding silently while only the clarification is
    visible. Returns None when nothing changed this turn.
    """

    def name(key: str) -> str:
        return majors.get(key, {}).get("display_name", key)

    if change.action == ACTION_REPLACE:
        added = ", ".join(name(o.major) for o in intent.add_options)
        if change.remove_majors:
            removed = ", ".join(name(m) for m in change.remove_majors)
            return f"You're now comparing {added} instead of {removed}."
        return f"Now comparing {added}."
    if change.action == ACTION_ADD:
        added = ", ".join(name(o.major) for o in intent.add_options)
        verb = "has" if len(intent.add_options) == 1 else "have"
        return f"{added} {verb} been added."
    if change.action == ACTION_REMOVE:
        removed = ", ".join(name(m) for m in intent.remove_options)
        verb = "has" if len(intent.remove_options) == 1 else "have"
        return f"{removed} {verb} been removed."
    if change.action == ACTION_RESTORE_ALL:
        return "All your previous alternatives are back in the comparison."
    return None


def _apply_option_change(session: ConversationSession, intent, change, majors: dict):
    """
    Handle the WHO half of a turn.

    `change` is intent_to_option_change(intent), computed once by the
    caller (handle_turn()) so it can also be used to build a mutation
    confirmation sentence when an analysis-only clarification is about to
    replace this turn's explanation -- see _mutation_confirmation().

    Returns:
      - None if nothing changed, or the change was applied with nothing
        left pending.
      - a major key (str) if exactly one newly-added option is missing its
        required transfer-credit figure -- the caller turns this into a
        deterministic ask.
      - a TurnResult if validation rejected the change outright (e.g. the
        net result would still exceed MAX_OPTIONS) -- the caller returns
        this immediately; no state was mutated.
    """
    if not change.changes_anything or change.action == ACTION_CLARIFY:
        # This turn doesn't continue any option-change instruction that
        # might have been pending -- per the discard-on-unrelated-turn
        # policy, a pending replacement doesn't survive a turn that isn't
        # about it. (A turn that DOES continue it reaches the success
        # path below, which already clears this on completion.)
        session.pending_option_action = None
        return None

    known = set(session.all_known_options())
    genuinely_new = [o for o in intent.add_options if o.major not in known]

    # A targeted replace ("replace Psych BA with Psych BS, keep the rest")
    # removes the outgoing major from the comparison entirely -- not just
    # deactivates it the way plain "drop X" does. This has to happen in
    # the SAME reconstruction as adding the incoming major, atomically:
    # doing it as two separate steps (add, THEN remove) would briefly
    # produce a too-large options list and spuriously fail MAX_OPTIONS
    # even though the net change is a like-for-like swap.
    anchor = session.inputs.current_major
    majors_to_drop_from_inputs: set[str] = set()
    if change.action == ACTION_REPLACE and change.remove_majors:
        majors_to_drop_from_inputs = {
            m for m in change.remove_majors if m != anchor and m in known
        }

    if genuinely_new or majors_to_drop_from_inputs:
        new_options = [
            o for o in session.inputs.options if o.major not in majors_to_drop_from_inputs
        ]
        for option in genuinely_new:
            new_options.append(
                ComparisonOption(
                    major=option.major, credits_transferable=option.credits_transferable
                )
            )
        try:
            new_inputs = MultiComparisonInputs(
                current_major=session.inputs.current_major,
                credits_completed=session.inputs.credits_completed,
                options=new_options,
                credits_source=session.inputs.credits_source,
                credits_source_date=session.inputs.credits_source_date,
                credits_in_progress=session.inputs.credits_in_progress,
            )
        except ValidationError as e:
            # Nothing was mutated (set_inputs hasn't run yet) -- the old
            # trusted comparison stays exactly as it was. Preserve what
            # WAS understood about the attempted change so a follow-up
            # ("ok, drop Business too then") can complete it instead of
            # starting over.
            session.pending_option_action = PendingOptionAction(
                action=change.action,
                remove_majors=list(change.remove_majors),
                add_majors=[o.major for o in intent.add_options],
            )
            return TurnResult(session=session, clarification=_first_validation_message(e))
        session.set_inputs(new_inputs)

    session.set_active_options(
        apply_option_change(
            change,
            session.active_options,
            anchor=session.inputs.current_major,
            all_known_options=session.all_known_options(),
        )
    )
    # A successfully applied change resolves anything that was pending.
    session.pending_option_action = None

    if len(genuinely_new) == 1 and genuinely_new[0].credits_transferable is None:
        return genuinely_new[0].major

    return None


def _pending_option_action_context(session: ConversationSession) -> dict | None:
    """Plain-dict form of session.pending_option_action for the
    classifier's context -- None when nothing is pending."""
    pending = session.pending_option_action
    if pending is None:
        return None
    return {
        "action": pending.action,
        "remove_majors": list(pending.remove_majors),
        "add_majors": list(pending.add_majors),
    }


def _pending_field_request_context(session: ConversationSession) -> dict | None:
    """Plain-dict form of session.pending_field_request for the
    classifier's context -- None when nothing is pending. Lets the
    classifier recognize a natural-language (not bare-number) reply as
    resolving the pending field, or explicitly determine it doesn't --
    see ConversationIntent.pending_field_value."""
    pending = session.pending_field_request
    if pending is None:
        return None
    return {"major": pending.major, "field": pending.field}


def _known_option_credits(session: ConversationSession) -> dict[str, int]:
    """Major key -> transfer-credit figure, for every option Fork already
    has a number for (active or not). Lets the classifier resolve an
    explicit "same credits transfer over" without guessing -- see
    ai.interface.classify_intent's known_option_credits parameter. Never
    includes an option with no figure yet; None is not a credits value."""
    if session.inputs is None:
        return {}
    return {
        o.major: o.credits_transferable
        for o in session.inputs.options
        if o.credits_transferable is not None
    }


def _resolve_pending_field(
    session: ConversationSession,
    value: int,
    reference_data: dict,
    explain=None,
    available_nodes: list[dict] | None = None,
    selected_detail_path: str | None = None,
) -> TurnResult | None:
    """
    Apply a value to the session's pending field request.

    Returns None ONLY when the pending option no longer exists at all
    (e.g. removed in a race) -- signalling "not applicable, fall through
    to normal classification." An invalid VALUE (fails validation) is a
    real, structured response, not a fall-through: the student is told
    why it didn't validate, and pending_field_request is left exactly as
    it was so they can just try again -- this is what keeps an invalid
    number from being silently forwarded to the classifier as though it
    were an unrelated message.

    On success, if a PendingAnalysisQuestion was waiting on this field
    (see the module docstring's auto-resume behavior), answers it
    automatically instead of returning a bare confirmation.
    """
    pending = session.pending_field_request
    option = session.inputs.option_for(pending.major) if session.inputs else None
    if option is None:
        session.pending_field_request = None
        session.pending_analysis_question = None
        return None

    updated_options = [
        ComparisonOption(
            major=o.major,
            credits_transferable=value if o.major == pending.major else o.credits_transferable,
            credits_transferable_source=o.credits_transferable_source,
            prospective_credits_required=o.prospective_credits_required,
            prospective_credits_required_source=o.prospective_credits_required_source,
        )
        for o in session.inputs.options
    ]
    try:
        new_inputs = MultiComparisonInputs(
            current_major=session.inputs.current_major,
            credits_completed=session.inputs.credits_completed,
            options=updated_options,
            credits_source=session.inputs.credits_source,
            credits_source_date=session.inputs.credits_source_date,
            credits_in_progress=session.inputs.credits_in_progress,
        )
    except ValidationError as e:
        return TurnResult(session=session, clarification=_first_validation_message(e))

    session.set_inputs(new_inputs)
    session.pending_field_request = None
    ensure_snapshot(session, reference_data, force=True)

    pending_question = session.pending_analysis_question
    session.pending_analysis_question = None
    display = reference_data["majors"][pending.major]["display_name"]

    if pending_question is not None and explain is not None:
        snapshot = session.snapshot
        view = build_view(
            snapshot,
            pending_question.topic_scope,
            session.active_options,
            session.stated_priority,
        )
        result = explain(view, pending_question.original_message, available_nodes=available_nodes)
        explanation = result["explanation"]
        explanation_dict = (
            explanation.model_dump() if hasattr(explanation, "model_dump") else explanation
        )
        related_node_ids = explanation_dict.get("related_node_ids", [])
        pills, target = _compute_navigation(
            related_node_ids, [], session.active_options, snapshot, selected_detail_path
        )
        return TurnResult(
            session=session,
            view=view,
            explanation=explanation_dict,
            used_fallback=result.get("used_fallback", False),
            navigation_pills=pills,
            navigation_target=target,
        )

    text = f"Got it -- {display} is now included in your comparison."
    return TurnResult(session=session, explanation=_ask_as_explanation(text))


def _first_validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "That option's inputs didn't validate."
    original = errors[0].get("ctx", {}).get("error")
    message = str(original) if original is not None else errors[0]["msg"]
    return message.removeprefix("Value error, ")


@dataclass
class PairwiseTurnIntent:
    """
    What one Compare One chat turn resolved to, before the actual
    calculation/explanation step -- main.py still owns that, since it
    already has _run_change_major_calculation and the recompute-from-
    client-supplied-inputs trust boundary that makes /explain safe.

    Exactly one of `clarification`, `short_circuit_explanation`, or
    (`topic_scope` set, ready to explain) applies -- see handle_pairwise_turn.
    """

    session: ConversationSession
    ai_unavailable: bool = False
    clarification: str | None = None
    topic_scope: str | None = None
    # Set whenever this turn resolved a "replace" -- the frontend applies
    # this to its draft form and, only when credits_transferable is
    # present, re-runs the existing calculate/explain flow with it. When
    # credits_transferable is None, nothing is recalculated yet; the
    # accompanying short_circuit_explanation asks for it.
    applied_option_change: dict | None = None
    short_circuit_explanation: dict | None = None
    referenced_majors: list[str] = field(default_factory=list)

    @property
    def needs_clarification(self) -> bool:
        return self.clarification is not None


_PAIRWISE_OPTION_CHANGE_UNSUPPORTED = (
    "Compare One looks at one alternative at a time. To switch what "
    "you're comparing against, tell me the major directly (\"compare me "
    "to Computer Science instead\") -- or switch to Compare Multiple to "
    "line up several alternatives at once."
)


def handle_pairwise_turn(
    session: ConversationSession,
    message: str,
    current_major: str,
    prospective_major: str,
    credits_completed: int,
    valid_majors: dict[str, str],
    classify=None,
) -> PairwiseTurnIntent:
    """
    Compare One's counterpart to handle_turn(). Resolves intent, priority,
    and (replace-only) option-change handling for a pairwise conversation.
    Never computes a projection itself -- that stays main.py's job, using
    the same recompute-from-client-supplied-inputs path /explain always
    has, so a replace with a stated transfer figure is applied through
    the exact same trust boundary as a manual form submission.

    Critically, `credits_transferable` for a NEW prospective major never
    comes from anywhere but this turn's own classified intent (or a
    subsequent bare-number reply) -- the old major's figure, which may
    still be sitting in the request that carries this message, is never
    read for this purpose. See the architecture plan's regression test
    for exactly the bug this prevents.
    """
    if classify is None:
        from ai.interface import classify_intent

        classify = classify_intent

    # --- pending field: bare-number fast path, no AI call ----------------
    if session.pending_field_request is not None:
        match = _BARE_NUMBER_RE.match(message.strip())
        if match:
            pending = session.pending_field_request
            session.pending_field_request = None
            return PairwiseTurnIntent(
                session=session,
                applied_option_change={
                    "major": pending.major,
                    "credits_transferable": int(match.group(1)),
                },
            )

    intent = classify(
        message,
        valid_majors,
        current_topic_scope=session.current_topic_scope if session.turns else None,
        active_options=[current_major, prospective_major],
        stated_priority=session.stated_priority,
        selected_detail_path=None,
        pending_field_request=_pending_field_request_context(session),
    )

    if intent is None:
        return PairwiseTurnIntent(session=session, ai_unavailable=True)

    # --- pending field: natural-language resolution or release -----------
    # Same policy as Compare Multiple's handle_turn() -- a reply that
    # doesn't match the bare-number fast path still gets a real chance to
    # answer the pending field before that state is discarded. Compare
    # One has no pending-analysis-question/auto-resume concept (documented
    # limitation for this pass), so a resolved value here always just
    # produces an applied_option_change, same as the bare-number path.
    if session.pending_field_request is not None:
        pending = session.pending_field_request
        if intent.pending_field_value is not None:
            session.pending_field_request = None
            return PairwiseTurnIntent(
                session=session,
                applied_option_change={
                    "major": pending.major,
                    "credits_transferable": intent.pending_field_value,
                },
            )
        session.pending_field_request = None

    if intent.needs_clarification:
        text = clarification_message(
            intent.clarification_type,
            majors={k: {"display_name": v} for k, v in valid_majors.items()},
            ambiguous_candidates=intent.ambiguous_candidates,
            option_change_action=intent.option_change,
            active_options=[current_major, prospective_major],
        )
        session.record_turn(message, session.current_topic_scope, "clarification", intent.referenced_majors)
        return PairwiseTurnIntent(session=session, clarification=text)

    session.apply_priority_update(intent.priority_update)

    if intent.option_change == "replace" and intent.add_options:
        new_major = intent.add_options[0].major
        new_credits = intent.add_options[0].credits_transferable
        if new_credits is None:
            session.pending_field_request = PendingFieldRequest(
                major=new_major, field="credits_transferable"
            )
            display = valid_majors.get(new_major, new_major)
            text = f"How many of your {credits_completed} completed credits apply to {display}?"
            return PairwiseTurnIntent(
                session=session,
                short_circuit_explanation=_ask_as_explanation(text),
            )
        return PairwiseTurnIntent(
            session=session,
            applied_option_change={"major": new_major, "credits_transferable": new_credits},
        )

    if intent.option_change in ("add", "remove", "restore"):
        return PairwiseTurnIntent(session=session, clarification=_PAIRWISE_OPTION_CHANGE_UNSUPPORTED)

    routing = resolve_topic_scope(
        intent.topic_scope, session.current_topic_scope if session.turns else None
    )
    if routing.needs_clarification:
        session.record_turn(message, session.current_topic_scope, "clarification", intent.referenced_majors)
        return PairwiseTurnIntent(session=session, clarification=routing.clarification)

    session.set_topic_scope(
        routing.scope, "inherited" if intent.topic_scope == "unchanged" else "explicit"
    )
    session.record_turn(message, session.current_topic_scope, "explicit", intent.referenced_majors)

    return PairwiseTurnIntent(
        session=session, topic_scope=routing.scope, referenced_majors=intent.referenced_majors
    )


def compute_pairwise_navigation(related_node_ids: list[str]) -> tuple[list[dict], dict | None]:
    """Compare One's simpler counterpart to _compute_navigation -- there's
    only ever one path, so pills never carry a major label and a click
    never switches selected_detail_path."""
    nodes = list(dict.fromkeys(related_node_ids))
    pills = [{"major": None, "node_id": n} for n in nodes]
    target = {"major": None, "node_id": nodes[0]} if len(nodes) == 1 else None
    return pills, target


def _compute_navigation(
    related_node_ids: list[str],
    referenced_majors: list[str],
    active_options: list[str],
    snapshot: MultiComparisonSnapshot,
    current_path: str | None,
) -> tuple[list[dict], dict | None]:
    """
    Deterministic pill/auto-focus computation. Never authored by the
    explanation model -- only fed its already-validated related_node_ids.
    See the architecture plan's "Path-aware related-node navigation"
    section for the full reasoning; this is the code form of that table.

    Returns (navigation_pills, navigation_target).
    """
    if referenced_majors:
        majors_for_pills = list(dict.fromkeys(referenced_majors))
    else:
        majors_for_pills = [
            m
            for m in active_options
            if (o := snapshot.outcome_for(m)) is not None and o.status == STATUS_CALCULATED
        ]

    nodes = list(dict.fromkeys(related_node_ids))

    if len(nodes) == 0:
        pills: list[dict] = []
    elif len(nodes) == 1 and len(majors_for_pills) >= 1:
        # 1 node x N majors -> one path-aware pill per major.
        pills = [{"major": m, "node_id": nodes[0]} for m in majors_for_pills]
    elif len(nodes) > 1 and len(majors_for_pills) == 1:
        # N nodes x 1 major -> one pill per node. `major` still carries
        # the known path so a click can target it; the frontend decides
        # whether to SHOW the (redundant) major label from the pill set
        # as a whole, not from any single pill.
        pills = [{"major": majors_for_pills[0], "node_id": n} for n in nodes]
    else:
        # N nodes x N majors -- no matrix. Flat, path-less node pills.
        pills = [{"major": None, "node_id": n} for n in nodes]

    target = None
    if len(nodes) == 1:
        if not referenced_majors:
            target = {"major": None, "node_id": nodes[0]}
        elif len(referenced_majors) == 1:
            target = {"major": referenced_majors[0], "node_id": nodes[0]}

    return pills, target
