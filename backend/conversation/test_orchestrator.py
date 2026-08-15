"""
Full-conversation tests.

This is where the central requirement gets checked: active_options and
current_topic_scope are independent. The multi-turn sequence test walks
the exact conversation from the spec and asserts the option set survives
every topic change, and the topic survives every option change.

The AI is stubbed throughout. Nothing here needs a real model -- and the
fact that it doesn't is itself the point, since every fact in an answer
comes from the engine and the view, not from the model.
"""

import pytest

from conversation.orchestrator import handle_turn, start_comparison
from conversation.router import BROAD, CAREER, CREDITS, FINANCIAL, TIMELINE
from conversation.session import ConversationSession, SessionStore
from decision_paths.change_major.comparison_inputs import (
    ComparisonOption,
    MultiComparisonInputs,
)


def _reference_data() -> dict:
    def major(display, required, earnings_value):
        return {
            "display_name": display,
            "official_program_name": f"BS in {display}",
            "degree_type": "BS",
            "credits_required": required,
            "credits_required_source": "Test catalog",
            "credits_required_source_date": "2026-01-01",
            "earnings": {
                "1yr": {
                    "value": earnings_value,
                    "status": "available",
                    "status_note": None,
                    "label": "Median earnings 1 year after graduation",
                    "graduates_measured": 100,
                },
                "4yr": {
                    "value": None, "status": "unavailable", "status_note": "n/a",
                    "label": "Median earnings 4 years after graduation",
                    "graduates_measured": None,
                },
                "5yr": {
                    "value": None, "status": "unavailable", "status_note": "n/a",
                    "label": "Median earnings 5 years after graduation",
                    "graduates_measured": None,
                },
                "cip_4_digit": "11.01",
                "cip_title": "Computer Science",
                "degrees_awarded_in_field": 200,
                "shared_note": None,
                "source": "College Scorecard",
                "source_url": None,
                "dataset_release": "2024",
                "retrieved": "2026-01-01",
                "credential_level_label": "Bachelor's",
                "population_note": "Federally aided graduates only.",
            },
            "occupations": {
                "list": [], "crosswalk_source": "CIP-SOC",
                "crosswalk_source_url": None,
                "crosswalk_limitation": "Relatedness is expert judgment.",
                "wage_source": "BLS OEWS", "wage_release": "2024",
                "projections_source": "BLS EP", "projections_cycle": "2024-2034",
                "retrieved": "2026-01-01",
            },
        }

    return {
        "institution": {
            "name": "Test University",
            "tuition": {
                "full_time_semester_estimate": 5000.0,
                "full_time_semester_estimate_source": "Test bursar",
                "full_time_semester_estimate_source_date": "2026-01-01",
                "full_time_credit_threshold": 12,
                "below_full_time_note": "Hourly below 12.",
            },
        },
        "majors": {
            "psychology": major("Psychology", 120, 30396),
            "computer_science": major("Computer Science", 120, 70235),
            "information_technology": major("Information Technology", 120, 70235),
            "mechanical_engineering": major("Mechanical Engineering", 128, 68000),
        },
        "credits_per_semester_full_time": 15,
    }


class FakeExplain:
    """Records the view it was handed so tests can assert on what the
    model would have been allowed to see."""

    def __init__(self):
        self.views = []

    def __call__(self, view, question):
        self.views.append(view)
        return {
            "explanation": {"direct_answer": "stub", "key_points": []},
            "used_fallback": False,
        }

    @property
    def last_view(self):
        return self.views[-1]


@pytest.fixture
def session_and_data():
    data = _reference_data()
    session = ConversationSession(session_id="test")
    inputs = MultiComparisonInputs(
        current_major="psychology",
        credits_completed=72,
        options=[
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="information_technology", credits_transferable=69),
            ComparisonOption(major="mechanical_engineering", credits_transferable=54),
        ],
    )
    start_comparison(session, inputs, data)
    return session, data


def _majors_in(view):
    return [o["major"] for o in view["options"]]


# --- setup ----------------------------------------------------------------


def test_starting_a_comparison_activates_every_major(session_and_data):
    session, _ = session_and_data
    assert session.active_options == [
        "psychology",
        "computer_science",
        "information_technology",
        "mechanical_engineering",
    ]
    assert session.current_topic_scope == BROAD
    assert len(session.snapshot.calculated()) == 3


# --- the spec's conversation, turn by turn --------------------------------


def test_full_conversation_keeps_who_and_what_independent(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()

    def ask(message):
        return handle_turn(session, message, data, explain=explain)

    # Broad question, all four.
    ask("What are the big tradeoffs here?")
    assert session.current_topic_scope == BROAD
    assert len(session.active_options) == 4
    assert len(_majors_in(explain.last_view)) == 3  # three alternatives

    # Topic narrows to cost. Options must NOT narrow.
    ask("Which one costs me more?")
    assert session.current_topic_scope == FINANCIAL
    assert len(session.active_options) == 4
    assert len(_majors_in(explain.last_view)) == 3

    # Vague follow-up inherits financial, options still untouched.
    ask("Okay, what's working against me?")
    assert session.current_topic_scope == FINANCIAL
    assert session.last_question_intent == "inherited"
    assert len(session.active_options) == 4

    # Topic switches to career. Options STILL untouched.
    ask("What about jobs?")
    assert session.current_topic_scope == CAREER
    assert len(session.active_options) == 4

    # A preference statement. Nothing changes at all.
    ask("Mechanical looks rough honestly")
    assert len(session.active_options) == 4
    assert "mechanical_engineering" in session.active_options

    # Explicit narrowing. Topic must SURVIVE the option change.
    ask("Just compare CS and IT")
    assert session.active_options == [
        "psychology",
        "computer_science",
        "information_technology",
    ]
    assert session.current_topic_scope == CAREER

    # New topic on the narrowed set.
    ask("Which one gets me out faster?")
    assert session.current_topic_scope == TIMELINE
    assert len(session.active_options) == 3
    assert len(_majors_in(explain.last_view)) == 2

    # Widen the options again. Topic survives again.
    ask("Actually put all four back")
    assert len(session.active_options) == 4
    assert session.current_topic_scope == TIMELINE


# --- the two rules, isolated ---------------------------------------------


def test_topic_change_never_touches_options(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    before = list(session.active_options)

    for message in [
        "Which one costs more?",
        "What about careers?",
        "How long will each take?",
        "What happens to my credits?",
    ]:
        handle_turn(session, message, data, explain=explain)
        assert session.active_options == before


def test_option_change_never_touches_topic(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()

    handle_turn(session, "Which one costs more?", data, explain=explain)
    assert session.current_topic_scope == FINANCIAL

    handle_turn(session, "Drop Mechanical Engineering", data, explain=explain)
    assert session.current_topic_scope == FINANCIAL


def test_preference_statements_never_narrow_the_comparison(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    before = list(session.active_options)

    for message in [
        "I'm leaning toward IT",
        "Computer Science sounds more interesting",
        "Psychology seems expensive",
        "Tell me more about Computer Science",
    ]:
        handle_turn(session, message, data, explain=explain)
        assert session.active_options == before, f"'{message}' changed the options"


# --- clarification --------------------------------------------------------


def test_ambiguous_option_instruction_changes_nothing(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    before = list(session.active_options)
    scope_before = session.current_topic_scope

    result = handle_turn(session, "Let's just focus on those two", data, explain=explain)

    assert result.needs_clarification
    assert session.active_options == before
    assert session.current_topic_scope == scope_before
    assert explain.views == []  # no answer was generated


def test_verdict_question_gets_a_redirect_not_a_ranking(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()

    result = handle_turn(session, "So which one is better?", data, explain=explain)

    assert result.needs_clarification
    assert "doesn't pick a winner" in result.clarification
    assert explain.views == []


# --- pending options ------------------------------------------------------


def test_pending_option_stays_in_the_conversation():
    data = _reference_data()
    session = ConversationSession(session_id="test")
    inputs = MultiComparisonInputs(
        current_major="psychology",
        credits_completed=72,
        options=[
            ComparisonOption(major="computer_science", credits_transferable=66),
            ComparisonOption(major="mechanical_engineering"),
        ],
    )
    start_comparison(session, inputs, data)
    explain = FakeExplain()

    handle_turn(session, "Compare these", data, explain=explain)

    view_majors = _majors_in(explain.last_view)
    assert "Mechanical Engineering" in view_majors
    pending = [o for o in explain.last_view["options"] if o["status"] == "pending"][0]
    assert "data" not in pending
    assert pending["missing_fields"] == ["credits_transferable"]


# --- trusted state vs conversation state ---------------------------------


def test_no_ai_output_is_ever_stored_on_the_session(session_and_data):
    """The structural guarantee behind 'previous AI prose is not
    evidence': there is nowhere to put it."""
    session, data = session_and_data
    handle_turn(session, "Which one costs more?", data, explain=FakeExplain())

    turn = session.turns[-1]
    stored = set(turn.__dict__)
    assert stored == {"text", "topic_scope", "question_intent", "referenced_options"}
    assert turn.text == "Which one costs more?"


def test_snapshot_rebuilds_when_inputs_change(session_and_data):
    """A corrected credit count must not leave a stale snapshot describing
    a decision that no longer exists."""
    session, data = session_and_data
    first = session.snapshot

    corrected = MultiComparisonInputs(
        current_major="psychology",
        credits_completed=90,
        options=[ComparisonOption(major="computer_science", credits_transferable=80)],
    )
    start_comparison(session, corrected, data)

    assert session.snapshot is not first
    tuition = session.snapshot.calculated()[0].dimensions["financial"]
    assert tuition["incremental_tuition"]["value"] is not None


def test_snapshot_is_reused_when_inputs_are_unchanged(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    first = session.snapshot

    handle_turn(session, "Which one costs more?", data, explain=explain)
    handle_turn(session, "What about careers?", data, explain=explain)

    assert session.snapshot is first


# --- session store --------------------------------------------------------


def test_missing_session_id_creates_a_new_session():
    store = SessionStore()
    created = store.get_or_create(None)
    assert store.get(created.session_id) is created


def test_expired_session_id_creates_a_new_one_rather_than_failing():
    store = SessionStore(ttl_seconds=-1)
    old = store.create()
    replacement = store.get_or_create(old.session_id)
    assert replacement.session_id != old.session_id
