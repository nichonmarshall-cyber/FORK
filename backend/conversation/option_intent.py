"""
Decides WHO is being compared, when the student says so in plain language.

Natural-language understanding itself lives in ai.interface.classify_intent()
now -- this file used to also carry a regex/marker-based
detect_option_change() that did the understanding directly, but that's
exactly the brittle, ever-growing phrase table the architecture moved away
from. What's left here is the deterministic half that was never keyword
matching to begin with: turning an already-classified, already-validated
instruction into a new active_options list.

The hard requirement this file exists to enforce: expressing a preference
is not the same as changing the comparison. "I'm leaning toward IT" must
leave all four majors in play. That distinction is now the classifier's
job (see ai.interface.INTENT_SYSTEM_PROMPT's OPTION CHANGES section) --
only an explicit instruction ever produces option_change != "none".

Major keys arriving here have already been validated against the
institution's real majors table by
ai.interface._validate_intent()/classify_intent() -- nothing in this file
re-derives them from free text.
"""

from dataclasses import dataclass, field

# What the student asked to do with the comparison set.
ACTION_NONE = "none"
ACTION_REPLACE = "replace"
ACTION_ADD = "add"
ACTION_REMOVE = "remove"
ACTION_RESTORE_ALL = "restore_all"
ACTION_CLARIFY = "clarify"

# Maps the intent schema's option_change literal onto this module's action
# constants. "unclear" always becomes ACTION_CLARIFY -- the classifier
# already decided it couldn't confidently resolve which majors were meant.
_INTENT_ACTION_MAP = {
    "none": ACTION_NONE,
    "replace": ACTION_REPLACE,
    "add": ACTION_ADD,
    "remove": ACTION_REMOVE,
    "restore": ACTION_RESTORE_ALL,
    "unclear": ACTION_CLARIFY,
}


@dataclass
class OptionChange:
    action: str
    majors: list[str] = field(default_factory=list)
    # Only meaningful for ACTION_REPLACE. Empty means "wholesale narrow"
    # ("just compare CS and IT" -- the active set becomes exactly `majors`).
    # Non-empty means "targeted swap" ("replace Psych BA with Psych BS,
    # keep the rest" -- these specific majors leave, `majors` are added,
    # everyone else stays). See apply_option_change()'s ACTION_REPLACE
    # branch for why this distinction has to exist: these are genuinely
    # different instructions that happen to share one action name.
    remove_majors: list[str] = field(default_factory=list)
    clarification: str | None = None

    @property
    def changes_anything(self) -> bool:
        return self.action not in (ACTION_NONE, ACTION_CLARIFY)


def intent_to_option_change(intent) -> "OptionChange":
    """
    Adapt a validated ConversationIntent (ai.interface.ConversationIntent)
    into the OptionChange shape apply_option_change() already knows how to
    execute. Pure reshaping -- the major keys were already checked against
    the institution's real majors table upstream (_validate_intent()).

    Callers check intent.needs_clarification themselves BEFORE reaching
    this function (see conversation.orchestrator.handle_turn) -- a turn
    that needs clarification never gets this far, so this function
    doesn't need to re-check it.

    `majors` carries the ADD or REMOVE major list depending on `action`,
    matching what apply_option_change() expects for each branch.
    `remove_majors` additionally carries the classifier's remove_options
    for a REPLACE -- present only when the student named specifically
    which major(s) to swap out (a targeted replace), absent for a
    wholesale "just compare X and Y" narrowing.

    A "restore" that names a major ("put Psychology back") is handled as
    an ACTION_ADD -- a previously-removed major is still sitting in
    session.inputs.options, just inactive, so reactivating it by name is
    exactly what ACTION_ADD's existing logic already does. Only a
    nameless "restore" ("put them all back") is the real
    ACTION_RESTORE_ALL. No new state-transition code is needed for this;
    it's a mapping decision, not new behavior.
    """
    action = _INTENT_ACTION_MAP.get(intent.option_change, ACTION_CLARIFY)
    if action == ACTION_RESTORE_ALL and intent.add_options:
        action = ACTION_ADD

    if action in (ACTION_REPLACE, ACTION_ADD):
        majors = [o.major for o in intent.add_options]
    elif action == ACTION_REMOVE:
        majors = list(intent.remove_options)
    else:
        majors = []

    remove_majors = list(intent.remove_options) if action == ACTION_REPLACE else []

    return OptionChange(action=action, majors=majors, remove_majors=remove_majors)


def clarification_for_option_change(
    action: str,
    active_options: list[str],
    remove_majors: list[str] | None = None,
    majors_by_key: dict | None = None,
) -> str:
    """
    Deterministic "which majors did you mean" prompt for an option-change
    instruction the classifier flagged as ambiguous (clarification_type
    "ambiguous_option_change" -- see ai.interface.ConversationIntent and
    conversation.router.clarification_message()). Reused verbatim across
    every ambiguous add/remove/replace case rather than model-authored,
    so the question itself can never invent or misname a major.

    `remove_majors`/`majors_by_key` let a targeted, half-resolved replace
    ("replace Psych BA with ???") ask specifically what it's still
    missing, instead of falling back to the generic "which major should I
    add?" phrasing regardless of what was actually being attempted --
    that mismatch (asking about "add" when the student asked to replace)
    is a real, previously-observed bug: the pending action has to survive
    into the clarification, not just the fact that something is unclear.
    """
    which = ", ".join(active_options) if active_options else "the current set"
    if action == ACTION_REPLACE:
        if remove_majors:
            names = [
                (majors_by_key or {}).get(m, {}).get("display_name", m) for m in remove_majors
            ]
            return f"Which major would you like to replace {', '.join(names)} with?"
        return f"Which majors should I compare? Right now it's {which}."
    if action == ACTION_REMOVE:
        return f"Which one should I drop? Right now it's {which}."
    if action == ACTION_ADD:
        return f"Which major should I add? Right now it's {which}."
    return f"I'm not sure which major(s) you mean — could you name them? Right now it's {which}."


def apply_option_change(
    change: OptionChange,
    active_options: list[str],
    anchor: str,
    all_known_options: list[str],
) -> list[str]:
    """
    Produce the new active option set.

    The anchor is never removable. It's the baseline every alternative is
    measured against, so a comparison without it isn't a narrower
    comparison — it's a different calculation this decision path doesn't
    support. A student saying "drop Psychology" while majoring in
    Psychology gets the set unchanged rather than a broken comparison.
    """
    if change.action == ACTION_RESTORE_ALL:
        return list(all_known_options)

    if change.action == ACTION_REPLACE:
        if change.remove_majors:
            # Targeted swap: these specific majors leave, the named ones
            # join, everyone else is untouched. "Replace Psych BA with
            # Psych BS, keep IT/Business/CS" must produce exactly
            # [anchor, IT, Business, CS, Psych BS] -- not a wholesale
            # narrow to just the named majors.
            removable = [m for m in change.remove_majors if m != anchor]
            out = [m for m in active_options if m not in removable]
            for major in change.majors:
                if major not in out:
                    out.append(major)
            return out if len(out) > 1 else list(active_options)
        # Wholesale narrow: "just compare CS and IT" -- the active set
        # becomes exactly the named majors (plus the anchor).
        rebuilt = [m for m in change.majors if m != anchor]
        return [anchor] + rebuilt if rebuilt else list(active_options)

    if change.action == ACTION_ADD:
        out = list(active_options)
        for major in change.majors:
            if major not in out:
                out.append(major)
        return out

    if change.action == ACTION_REMOVE:
        removable = [m for m in change.majors if m != anchor]
        out = [m for m in active_options if m not in removable]
        # Never leave the comparison with nothing to compare against.
        return out if len(out) > 1 else list(active_options)

    return list(active_options)
