"""
Tests for option-set changes.

The single most important group here is the preference tests. If Fork
drops majors from a comparison because someone said they liked one, the
student silently loses information they never agreed to give up. Those
tests are the guardrail on that.
"""

from conversation.option_intent import (
    ACTION_ADD,
    ACTION_CLARIFY,
    ACTION_NONE,
    ACTION_REMOVE,
    ACTION_REPLACE,
    ACTION_RESTORE_ALL,
    apply_option_change,
    build_major_lookup,
    detect_option_change,
)

MAJORS = {
    "psychology": {"display_name": "Psychology"},
    "computer_science": {"display_name": "Computer Science"},
    "information_technology": {"display_name": "Information Technology"},
    "mechanical_engineering": {"display_name": "Mechanical Engineering"},
}

LOOKUP = build_major_lookup(MAJORS)
ACTIVE = [
    "psychology",
    "computer_science",
    "information_technology",
    "mechanical_engineering",
]


def _detect(message):
    return detect_option_change(message, LOOKUP, ACTIVE)


# --- preference must never change the set --------------------------------


def test_leaning_toward_does_not_change_options():
    change = _detect("I'm leaning toward Computer Science")
    assert change.action == ACTION_NONE
    assert not change.changes_anything


def test_liking_a_major_does_not_change_options():
    assert _detect("I like Computer Science more").action == ACTION_NONE


def test_calling_a_major_expensive_does_not_change_options():
    assert _detect("Psychology looks expensive").action == ACTION_NONE


def test_asking_for_more_detail_does_not_change_options():
    """'Tell me more about CS' is a topic focus, not a request to delete
    the other three."""
    assert _detect("Tell me more about Computer Science").action == ACTION_NONE


def test_ordinary_question_does_not_change_options():
    assert _detect("Which one costs more?").action == ACTION_NONE


# --- explicit changes -----------------------------------------------------


def test_just_compare_narrows():
    change = _detect("Just compare Computer Science and IT")
    assert change.action == ACTION_REPLACE
    assert set(change.majors) == {"computer_science", "information_technology"}


def test_only_deciding_between_narrows():
    change = _detect("I'm only deciding between CS and IT now")
    assert change.action == ACTION_REPLACE
    assert set(change.majors) == {"computer_science", "information_technology"}


def test_drop_removes():
    change = _detect("Drop Psychology")
    assert change.action == ACTION_REMOVE
    assert change.majors == ["psychology"]


def test_add_back_adds():
    change = _detect("Add Mechanical Engineering back")
    assert change.action == ACTION_ADD
    assert change.majors == ["mechanical_engineering"]


def test_all_four_restores():
    assert _detect("Compare all four again").action == ACTION_RESTORE_ALL


def test_instruction_without_a_named_major_asks():
    change = _detect("Let's just compare these two")
    assert change.action == ACTION_CLARIFY
    assert not change.changes_anything
    assert "Which majors" in change.clarification


# --- the IT / "it" problem ------------------------------------------------


def test_lowercase_it_pronoun_is_not_information_technology():
    """'drop it' must not be read as 'drop Information Technology'. This
    was a real bug -- substring matching found IT inside ordinary words
    and pronouns."""
    change = _detect("drop it")
    assert "information_technology" not in change.majors


def test_uppercase_IT_is_the_major():
    change = _detect("Just compare CS and IT")
    assert "information_technology" in change.majors


def test_it_inside_another_word_is_not_a_major():
    change = _detect("Just compare Psychology with Computer Science")
    assert "information_technology" not in change.majors


def test_mechanical_does_not_double_match():
    change = _detect("Drop Mechanical Engineering")
    assert change.majors == ["mechanical_engineering"]


# --- applying the change --------------------------------------------------


def test_replace_keeps_the_anchor():
    change = _detect("Just compare CS and IT")
    result = apply_option_change(change, ACTIVE, "psychology", ACTIVE)
    assert result == ["psychology", "computer_science", "information_technology"]


def test_remove_drops_only_the_named_option():
    change = _detect("Drop Mechanical Engineering")
    result = apply_option_change(change, ACTIVE, "psychology", ACTIVE)
    assert "mechanical_engineering" not in result
    assert len(result) == 3


def test_anchor_cannot_be_removed():
    """A comparison with no baseline isn't a narrower comparison, it's a
    different calculation this path doesn't support."""
    change = _detect("Drop Psychology")
    result = apply_option_change(change, ACTIVE, "psychology", ACTIVE)
    assert result == ACTIVE


def test_restore_all_returns_everyone():
    narrowed = ["psychology", "computer_science"]
    change = _detect("Compare all four again")
    result = apply_option_change(change, narrowed, "psychology", ACTIVE)
    assert result == ACTIVE


def test_add_is_idempotent():
    change = _detect("Add Computer Science")
    result = apply_option_change(change, ACTIVE, "psychology", ACTIVE)
    assert result.count("computer_science") == 1


def test_removing_everything_leaves_the_set_alone():
    two = ["psychology", "computer_science"]
    change = _detect("Drop Computer Science")
    result = apply_option_change(change, two, "psychology", ACTIVE)
    assert result == two


def test_topic_focus_is_not_an_option_instruction():
    """'Let's focus on cost' matches a narrowing word but names no set of
    majors, so it must not trigger 'which majors did you mean?' -- that's
    a baffling reply to a question about money."""
    assert _detect("Let's focus on cost").action == ACTION_NONE
    assert _detect("Focus on the career side").action == ACTION_NONE


def test_focus_on_a_set_without_names_asks():
    change = _detect("Let's just focus on those two")
    assert change.action == ACTION_CLARIFY


def test_focus_on_named_majors_narrows():
    change = _detect("Let's focus on Computer Science and Psychology")
    assert change.action == ACTION_REPLACE
    assert set(change.majors) == {"computer_science", "psychology"}
