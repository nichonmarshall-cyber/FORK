"""
Decides WHO is being compared, when the student says so in plain language.

The hard requirement this file exists to enforce: expressing a preference
is not the same as changing the comparison. "I'm leaning toward IT" must
leave all four majors in play. If Fork quietly drops the other three
because someone said they liked one, the student loses information they
never agreed to give up, and they may not even notice it happened.

So the bar for changing active_options is an explicit comparison-set
instruction — "just compare X and Y", "drop X", "add X back". Everything
else leaves the set exactly as it was. When an instruction is clearly
meant to change the set but Fork can't tell which majors it refers to,
that's a clarification, not a guess.

Major names are matched against the institution's own major table rather
than a hardcoded list here, so adding a major to the data doesn't require
editing this file.
"""

import re
from dataclasses import dataclass, field

# What the student asked to do with the comparison set.
ACTION_NONE = "none"
ACTION_REPLACE = "replace"
ACTION_ADD = "add"
ACTION_REMOVE = "remove"
ACTION_RESTORE_ALL = "restore_all"
ACTION_CLARIFY = "clarify"


@dataclass
class OptionChange:
    action: str
    majors: list[str] = field(default_factory=list)
    clarification: str | None = None

    @property
    def changes_anything(self) -> bool:
        return self.action not in (ACTION_NONE, ACTION_CLARIFY)


# Explicit narrowing. "just compare X and Y" / "only looking at X and Y".
_REPLACE_MARKERS = (
    "just compare", "only compare", "compare just", "compare only",
    "just look at", "only look at", "just show", "only show",
    "focus on just", "just focus on", "focus on", "narrow to",
    "narrow it to", "limit to",
    "i'm only deciding between", "im only deciding between",
    "only deciding between", "just deciding between",
    "let's just do", "lets just do", "switch to comparing",
)

# Words that point at a SET of majors without naming them. Required before
# an instruction with no named major counts as an option change at all.
#
# This is what keeps "let's focus on cost" a topic instruction rather than
# an option one: it matches a narrowing marker but points at no set, so
# it's left alone entirely instead of triggering "which majors did you
# mean?" — which would be a baffling reply to a question about money.
_SET_REFERENTS = (
    "those two", "these two", "those three", "these three",
    "those four", "these four", "the two", "the three", "the other two",
    "the other three", "the others", "the rest", "just those",
    "just these", "them both", "both of them", "the ones",
)

_ADD_MARKERS = (
    "add ", "put back", "bring back", "include ", "also compare",
    "throw in", "add back",
)

_REMOVE_MARKERS = (
    "drop ", "remove ", "take out", "get rid of", "forget about",
    "cut ", "lose ", "without ",
)

_RESTORE_MARKERS = (
    "all four", "all three", "all of them", "everything again",
    "all the majors", "back to all", "compare all again", "all again",
    "put them all back", "restore",
)

# Preference and interest language. Present here ONLY so the intent behind
# excluding it is visible in code: if any of these show up without an
# explicit instruction above, the answer is ACTION_NONE. "Tell me more
# about CS" is a topic focus, not a request to delete IT and Psychology.
_PREFERENCE_MARKERS = (
    "leaning toward", "leaning towards", "i like", "i prefer", "sounds better",
    "sounds more", "seems better", "seems expensive", "looks expensive",
    "more interesting", "tell me more about", "what about just",
    "i'm interested in", "im interested in", "i want to do",
)


# "it" is a real abbreviation for Information Technology and also the most
# common pronoun in English. Substring matching would find it inside
# "limit", "with", and "credits"; even word-boundary matching would fire on
# "drop it". So it only counts when the student actually typed it in caps,
# which is how anyone referring to the major writes it.
_CASE_SENSITIVE_ALIASES = {"it": "information_technology"}

_IT_ALIAS_RE = re.compile(r"\bIT\b")


def _find_majors(
    message: str,
    major_lookup: dict[str, str],
) -> list[str]:
    """
    Majors named in the message, as canonical keys.

    Word-boundary matched, longest name first, and each match is blanked
    out afterward so a shorter alias sitting inside a longer name
    ("mechanical" inside "mechanical engineering") can't match the same
    words twice.

    Takes the ORIGINAL message rather than a lowercased one, because the
    IT alias needs the casing to tell the major from the pronoun.
    """
    text = message.lower()
    found: list[str] = []

    for name in sorted(major_lookup, key=len, reverse=True):
        if name in _CASE_SENSITIVE_ALIASES:
            continue
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        match = pattern.search(text)
        if match:
            key = major_lookup[name]
            if key not in found:
                found.append(key)
            text = pattern.sub(lambda m: " " * len(m.group()), text)

    # Now the caps-only check, against the untouched original.
    for alias, key in _CASE_SENSITIVE_ALIASES.items():
        if key in major_lookup.values() and _IT_ALIAS_RE.search(message):
            if key not in found:
                found.append(key)

    return found


def detect_option_change(
    message: str,
    major_lookup: dict[str, str],
    active_options: list[str],
) -> OptionChange:
    """
    Work out whether this message changes the comparison set.

    Returns ACTION_NONE for anything that isn't an explicit instruction —
    which is most messages, including every preference statement.
    """
    text = message.lower().strip()
    named = _find_majors(message, major_lookup)

    if any(m in text for m in _RESTORE_MARKERS):
        return OptionChange(action=ACTION_RESTORE_ALL)

    for markers, action in (
        (_REPLACE_MARKERS, ACTION_REPLACE),
        (_REMOVE_MARKERS, ACTION_REMOVE),
        (_ADD_MARKERS, ACTION_ADD),
    ):
        if any(m in text for m in markers):
            if named:
                return OptionChange(action=action, majors=named)
            if any(r in text for r in _SET_REFERENTS):
                # Clearly meant to change the set, but Fork can't tell
                # which majors. Ask — never guess, since guessing wrong
                # silently drops majors the student still wanted.
                return OptionChange(
                    action=ACTION_CLARIFY,
                    clarification=_clarification_for(action, active_options),
                )
            # Matched a narrowing word but points at no set of majors, so
            # it isn't an option instruction. Most likely a topic one.
            return OptionChange(action=ACTION_NONE)

    # Explicitly not a change. Preference language lands here, and so does
    # every ordinary question.
    return OptionChange(action=ACTION_NONE)


def _clarification_for(action: str, active_options: list[str]) -> str:
    which = ", ".join(active_options) if active_options else "the current set"
    if action == ACTION_REPLACE:
        return f"Which majors should I compare? Right now it's {which}."
    if action == ACTION_REMOVE:
        return f"Which one should I drop? Right now it's {which}."
    return f"Which major should I add? Right now it's {which}."


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


def build_major_lookup(majors: dict) -> dict[str, str]:
    """
    Lowercase display name -> major key, plus a few obvious shorthands
    students actually type. Built from institution data so it stays in
    step with whatever majors exist.
    """
    lookup: dict[str, str] = {}
    for key, entry in majors.items():
        display = entry.get("display_name")
        if display:
            lookup[display.lower()] = key
        lookup[key.replace("_", " ")] = key

    # Shorthands that aren't derivable from the display name. Only added
    # when the underlying major is actually present in the data.
    # "it" is present but handled case-sensitively in _find_majors — see
    # _CASE_SENSITIVE_ALIASES for why.
    #
    # Each alias is only added if the major it points at actually exists in
    # this institution's data, so a school without a given program never
    # gets an alias resolving to nothing.
    #
    # Psychology deliberately has NO shorthand. UNT offers it as two
    # distinct degrees (B.A. and B.S.) with different requirements, and
    # quietly resolving "psych" to one of them would be a silent wrong
    # answer of exactly the kind major_resolution.py exists to prevent.
    shorthands = {
        "cs": "computer_science",
        "comp sci": "computer_science",
        "compsci": "computer_science",
        "it": "information_technology",
        "info tech": "information_technology",
        "business": "business_administration",
        # UNT's program is "Mechanical & Energy Engineering", but nobody
        # types that. The older name is still what students say.
        "mechanical engineering": "mechanical_energy_engineering",
        "mechanical": "mechanical_energy_engineering",
        "mech e": "mechanical_energy_engineering",
        "meche": "mechanical_energy_engineering",
    }
    for alias, key in shorthands.items():
        if key in majors:
            lookup[alias] = key

    return lookup
