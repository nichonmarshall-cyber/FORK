"""
Tests for the deterministic half of option-change handling: turning an
already-classified instruction into a new active_options list, and
building the fixed clarification copy for an ambiguous one.

Natural-language understanding itself is tested against ai.interface's
classify_intent() (see ai/test_intent.py) and end-to-end against
handle_turn() with a stubbed classifier (see test_orchestrator.py) --
nothing here matches phrases, because nothing in option_intent.py does
anymore.
"""

from types import SimpleNamespace

from conversation.option_intent import (
    ACTION_ADD,
    ACTION_CLARIFY,
    ACTION_NONE,
    ACTION_REMOVE,
    ACTION_REPLACE,
    ACTION_RESTORE_ALL,
    apply_option_change,
    clarification_for_option_change,
    intent_to_option_change,
)


def _intent(**overrides):
    """A minimal stand-in for ai.interface.ConversationIntent -- only the
    fields intent_to_option_change() actually reads."""
    defaults = dict(option_change="none", add_options=[], remove_options=[])
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _opt(major, credits=None):
    return SimpleNamespace(major=major, credits_transferable=credits)


class TestIntentToOptionChange:
    def test_none_produces_no_change(self):
        change = intent_to_option_change(_intent())
        assert change.action == ACTION_NONE
        assert not change.changes_anything

    def test_add_carries_major_keys_from_add_options(self):
        change = intent_to_option_change(
            _intent(option_change="add", add_options=[_opt("computer_science", 61)])
        )
        assert change.action == ACTION_ADD
        assert change.majors == ["computer_science"]

    def test_replace_carries_major_keys_from_add_options(self):
        change = intent_to_option_change(
            _intent(option_change="replace", add_options=[_opt("psychology_bs")])
        )
        assert change.action == ACTION_REPLACE
        assert change.majors == ["psychology_bs"]

    def test_remove_carries_remove_options(self):
        change = intent_to_option_change(
            _intent(option_change="remove", remove_options=["business_administration"])
        )
        assert change.action == ACTION_REMOVE
        assert change.majors == ["business_administration"]

    def test_restore_with_no_named_major_maps_to_restore_all(self):
        change = intent_to_option_change(_intent(option_change="restore"))
        assert change.action == ACTION_RESTORE_ALL

    def test_restore_with_a_named_major_maps_to_add(self):
        """'Put Psychology back' names one major -- reuses ACTION_ADD's
        existing reactivation logic rather than restoring everyone."""
        change = intent_to_option_change(
            _intent(option_change="restore", add_options=[_opt("psychology_ba")])
        )
        assert change.action == ACTION_ADD
        assert change.majors == ["psychology_ba"]

    def test_unclear_maps_to_clarify(self):
        change = intent_to_option_change(_intent(option_change="unclear"))
        assert change.action == ACTION_CLARIFY


class TestApplyOptionChange:
    """Unchanged pure state-transition logic -- kept exactly as it was
    before this file's rewrite, since it never did any keyword matching."""

    def test_add_appends_without_duplicating(self):
        change = SimpleNamespace(action=ACTION_ADD, majors=["computer_science"])
        result = apply_option_change(
            change,
            active_options=["psychology_ba", "information_technology"],
            anchor="psychology_ba",
            all_known_options=["psychology_ba", "information_technology", "computer_science"],
        )
        assert result == ["psychology_ba", "information_technology", "computer_science"]

    def test_remove_never_removes_the_anchor(self):
        change = SimpleNamespace(action=ACTION_REMOVE, majors=["psychology_ba"])
        result = apply_option_change(
            change,
            active_options=["psychology_ba", "information_technology"],
            anchor="psychology_ba",
            all_known_options=["psychology_ba", "information_technology"],
        )
        assert result == ["psychology_ba", "information_technology"]

    def test_remove_never_empties_the_comparison(self):
        change = SimpleNamespace(action=ACTION_REMOVE, majors=["information_technology"])
        result = apply_option_change(
            change,
            active_options=["psychology_ba", "information_technology"],
            anchor="psychology_ba",
            all_known_options=["psychology_ba", "information_technology"],
        )
        # Removing the only alternative would leave nothing to compare
        # against, so the set stays unchanged rather than collapsing to
        # just the anchor.
        assert result == ["psychology_ba", "information_technology"]

    def test_replace_with_no_remove_majors_is_a_wholesale_narrow(self):
        """'Just compare CS and IT' -- no remove_majors named, so the
        active set becomes exactly the named majors, dropping everyone
        else not mentioned."""
        change = SimpleNamespace(
            action=ACTION_REPLACE, majors=["computer_science"], remove_majors=[]
        )
        result = apply_option_change(
            change,
            active_options=["psychology_ba", "information_technology"],
            anchor="psychology_ba",
            all_known_options=["psychology_ba", "information_technology", "computer_science"],
        )
        assert result == ["psychology_ba", "computer_science"]

    def test_replace_with_remove_majors_is_a_targeted_swap(self):
        """'Replace Psych BA with Psych BS, keep IT/Business/CS' -- only
        the named remove_majors leave; everyone else stays. This is a
        genuinely different outcome from the wholesale-narrow case above,
        even though both are ACTION_REPLACE."""
        change = SimpleNamespace(
            action=ACTION_REPLACE,
            majors=["psychology_bs"],
            remove_majors=["psychology_ba"],
        )
        result = apply_option_change(
            change,
            active_options=[
                "information_technology",
                "business_administration",
                "computer_science",
                "psychology_ba",
            ],
            anchor="mechanical_energy_engineering",
            all_known_options=[
                "mechanical_energy_engineering",
                "information_technology",
                "business_administration",
                "computer_science",
                "psychology_ba",
                "psychology_bs",
            ],
        )
        assert result == [
            "information_technology",
            "business_administration",
            "computer_science",
            "psychology_bs",
        ]

    def test_restore_all_returns_every_known_option(self):
        change = SimpleNamespace(action=ACTION_RESTORE_ALL, majors=[])
        result = apply_option_change(
            change,
            active_options=["psychology_ba"],
            anchor="psychology_ba",
            all_known_options=["psychology_ba", "information_technology", "computer_science"],
        )
        assert result == ["psychology_ba", "information_technology", "computer_science"]


class TestClarificationForOptionChange:
    def test_replace_asks_which_majors(self):
        text = clarification_for_option_change(ACTION_REPLACE, ["psychology_ba", "computer_science"])
        assert "Which majors" in text
        assert "psychology_ba" in text

    def test_remove_asks_which_one(self):
        text = clarification_for_option_change(ACTION_REMOVE, ["psychology_ba"])
        assert "Which one" in text

    def test_add_asks_which_major(self):
        text = clarification_for_option_change(ACTION_ADD, ["psychology_ba"])
        assert "Which major" in text

    def test_empty_active_options_still_produces_readable_text(self):
        text = clarification_for_option_change(ACTION_ADD, [])
        assert "the current set" in text

    def test_replace_with_known_remove_majors_asks_what_to_replace_it_with(self):
        """The bug this guards against: an unresolved REPLACE must never
        be phrased as an ADD question ("which major should I add?") just
        because the target major wasn't named yet -- the pending action
        has to survive into the clarification."""
        text = clarification_for_option_change(
            ACTION_REPLACE,
            ["mechanical_energy_engineering", "information_technology"],
            remove_majors=["psychology_ba"],
            majors_by_key={"psychology_ba": {"display_name": "Psychology (B.A.)"}},
        )
        assert "replace Psychology (B.A.) with" in text
        assert "should I add" not in text.lower()
