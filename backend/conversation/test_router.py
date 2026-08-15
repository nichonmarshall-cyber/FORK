"""
Tests for topic routing.

The behavior that matters most here is inheritance: a student shouldn't
have to say "financially" in every message to stay on the subject of
money. The second is that routing NEVER touches the option set -- that's
covered in the orchestrator tests, but it's the reason this module has no
knowledge of active_options at all.
"""

from conversation.router import (
    BROAD,
    CAREER,
    CREDITS,
    FINANCIAL,
    INTENT_AMBIGUOUS,
    INTENT_DEFAULT_BROAD,
    INTENT_EXPLICIT,
    INTENT_INHERITED,
    TIMELINE,
    route_question,
)


# --- explicit topic signals ---------------------------------------------


def test_cost_question_routes_financial():
    d = route_question("Which one costs me more?")
    assert d.scope == FINANCIAL
    assert d.intent == INTENT_EXPLICIT


def test_career_question_routes_career():
    assert route_question("How do the careers compare?").scope == CAREER
    assert route_question("What kind of salary can I expect?").scope == CAREER


def test_timeline_question_routes_timeline():
    assert route_question("Will I graduate later?").scope == TIMELINE
    assert route_question("How long until I finish?").scope == TIMELINE


def test_credits_question_routes_credits():
    assert route_question("What happens to my credits?").scope == CREDITS
    assert route_question("Do my classes transfer?").scope == CREDITS


# --- broad markers beat inheritance -------------------------------------


def test_broad_question_routes_broad():
    d = route_question("Compare these majors")
    assert d.scope == BROAD
    assert d.intent == INTENT_EXPLICIT


def test_biggest_difference_is_broad_not_a_ranking_request():
    assert route_question("What's the biggest difference?").scope == BROAD


def test_explicit_broad_overrides_a_narrow_current_scope():
    """The bug this prevents: asking to widen right after a cost question
    and getting another cost answer because inheritance fired first."""
    d = route_question("What are the tradeoffs overall?", current_scope=FINANCIAL)
    assert d.scope == BROAD
    assert d.intent == INTENT_EXPLICIT


# --- inheritance ---------------------------------------------------------


def test_followup_with_no_topic_words_inherits():
    d = route_question("Okay, what's working against me?", current_scope=FINANCIAL)
    assert d.scope == FINANCIAL
    assert d.intent == INTENT_INHERITED


def test_short_continuation_inherits():
    d = route_question("And Mechanical?", current_scope=CAREER)
    assert d.scope == CAREER
    assert d.intent == INTENT_INHERITED


def test_explicit_topic_switch_beats_inheritance():
    d = route_question("What about jobs?", current_scope=FINANCIAL)
    assert d.scope == CAREER
    assert d.intent == INTENT_EXPLICIT


def test_the_documented_three_turn_sequence():
    """Straight from the spec: cost, then a vague follow-up, then careers."""
    first = route_question("Which one costs more?")
    assert first.scope == FINANCIAL

    second = route_question("Okay, what's working against me?", current_scope=first.scope)
    assert second.scope == FINANCIAL

    third = route_question("What about careers?", current_scope=second.scope)
    assert third.scope == CAREER


# --- defaults and ambiguity ----------------------------------------------


def test_first_turn_with_no_context_defaults_broad():
    d = route_question("Tell me about these options", current_scope=None)
    assert d.scope == BROAD
    assert d.intent == INTENT_DEFAULT_BROAD


def test_verdict_seeking_question_asks_rather_than_answering():
    """Fork doesn't pick a winner, so 'which is better' gets a redirect,
    not a ranking."""
    d = route_question("Which one is better?", current_scope=FINANCIAL)
    assert d.needs_clarification
    assert d.intent == INTENT_AMBIGUOUS
    assert d.scope is None
    assert "doesn't pick a winner" in d.clarification


def test_clarification_does_not_propose_a_scope():
    d = route_question("What should I do?", current_scope=CAREER)
    assert d.scope is None


def test_empty_message_keeps_current_scope():
    assert route_question("   ", current_scope=TIMELINE).scope == TIMELINE
