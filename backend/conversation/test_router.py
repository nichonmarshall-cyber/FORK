"""
Tests for the deterministic mapping from a classified topic_scope onto a
concrete scope, and the fixed clarification copy for each
clarification_type. Natural-language understanding is tested against
ai.interface's classify_intent() (ai/test_intent.py) and end-to-end
against handle_turn() with a stubbed classifier (test_orchestrator.py) --
nothing here matches phrases, because nothing in router.py does anymore.
"""

from conversation.router import (
    BROAD,
    CAREER,
    CREDITS,
    FINANCIAL,
    TIMELINE,
    UNCLEAR_TOPIC_MESSAGE,
    VERDICT_WITHOUT_PRIORITY_MESSAGE,
    ambiguous_major_message,
    clarification_message,
    resolve_topic_scope,
)

_MAJORS = {
    "psychology_ba": {"display_name": "Psychology (B.A.)"},
    "psychology_bs": {"display_name": "Psychology (B.S.)"},
    "computer_science": {"display_name": "Computer Science"},
}


class TestResolveTopicScope:
    def test_explicit_scope_passes_through(self):
        for scope in (BROAD, FINANCIAL, CAREER, TIMELINE, CREDITS):
            decision = resolve_topic_scope(scope, current_scope=None)
            assert decision.scope == scope
            assert not decision.needs_clarification

    def test_unchanged_inherits_prior_scope(self):
        decision = resolve_topic_scope("unchanged", current_scope=FINANCIAL)
        assert decision.scope == FINANCIAL
        assert not decision.needs_clarification

    def test_unchanged_with_no_prior_scope_asks_rather_than_guesses(self):
        """The classifier itself didn't fail here -- it just named
        something code can't resolve on a first turn. This must be a
        deterministic clarification, never an ai_unavailable-style
        failure and never a silent default to broad."""
        decision = resolve_topic_scope("unchanged", current_scope=None)
        assert decision.scope is None
        assert decision.needs_clarification
        assert decision.clarification == UNCLEAR_TOPIC_MESSAGE

    def test_unclear_asks_rather_than_guesses(self):
        decision = resolve_topic_scope("unclear", current_scope=FINANCIAL)
        assert decision.scope is None
        assert decision.needs_clarification


class TestClarificationMessage:
    def test_ambiguous_major_lists_real_display_names(self):
        text = clarification_message(
            "ambiguous_major",
            majors=_MAJORS,
            ambiguous_candidates=["psychology_ba", "psychology_bs"],
        )
        assert "Psychology (B.A.)" in text
        assert "Psychology (B.S.)" in text

    def test_ambiguous_option_change_reuses_option_intent_template(self):
        text = clarification_message(
            "ambiguous_option_change",
            majors=_MAJORS,
            option_change_action="remove",
            active_options=["computer_science"],
        )
        assert "Which one" in text

    def test_verdict_without_priority_is_the_fixed_message(self):
        text = clarification_message("verdict_without_priority", majors=_MAJORS)
        assert text == VERDICT_WITHOUT_PRIORITY_MESSAGE

    def test_conflicting_priority_has_its_own_message(self):
        text = clarification_message("conflicting_priority", majors=_MAJORS)
        assert "priority" in text.lower()

    def test_unclear_topic_falls_back_to_the_topic_menu(self):
        text = clarification_message("unclear_topic", majors=_MAJORS)
        assert text == UNCLEAR_TOPIC_MESSAGE

    def test_unknown_clarification_type_defaults_safely(self):
        # Defensive: a clarification_type the schema shouldn't allow
        # through still produces something readable rather than crashing.
        text = clarification_message(None, majors=_MAJORS)
        assert text == UNCLEAR_TOPIC_MESSAGE


class TestAmbiguousMajorMessage:
    def test_two_candidates_uses_and(self):
        text = ambiguous_major_message(["psychology_ba", "psychology_bs"], _MAJORS)
        assert "and" in text

    def test_unresolvable_candidates_still_asks(self):
        text = ambiguous_major_message(["not_a_real_key"], _MAJORS)
        assert "Which major" in text
