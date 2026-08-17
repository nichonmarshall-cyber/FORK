"""
Full-conversation tests.

This is where the central requirement gets checked: active_options,
current_topic_scope, and stated_priority are independent. The multi-turn
sequence test walks the exact conversation from the spec and asserts the
option set survives every topic change, the topic survives every option
change, and neither ever touches a stated priority.

Both the intent classifier and the explanation model are stubbed
throughout. Nothing here needs a real model call -- and the fact that it
doesn't is itself the point: every fact in an answer comes from the
engine and the view, and every piece of state comes from a validated,
scripted ConversationIntent, never from string matching against the
message text.
"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ai.interface import ConversationIntent, OptionMajorInput
from conversation.orchestrator import (
    compute_pairwise_navigation,
    handle_pairwise_turn,
    handle_turn,
    start_comparison,
)
from conversation.router import BROAD, CAREER, CREDITS, FINANCIAL, TIMELINE
from conversation.session import ConversationSession, SessionStore
from decision_paths.change_major.comparison_inputs import (
    MAX_OPTIONS,
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
                "list": [{
                    "title": "Software Developers",
                    "median_annual_wage": 130000,
                    "national_employment": 1600000,
                    "percent_change_2024_2034": 17.9,
                    "annual_openings": 150000,
                    "typical_education": "Bachelor's degree",
                }],
                "crosswalk_source": "CIP-SOC",
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
            "psychology_ba": major("Psychology (B.A.)", 120, 30396),
            "psychology_bs": major("Psychology (B.S.)", 120, 32000),
            "computer_science": major("Computer Science", 120, 70235),
            "information_technology": major("Information Technology", 120, 70235),
            "mechanical_engineering": major("Mechanical Engineering", 128, 68000),
            "business_administration": major("Business Administration", 120, 60000),
            "biology": major("Biology", 120, 45000),
        },
        "credits_per_semester_full_time": 15,
    }


class FakeExplain:
    """Records the view (and available_nodes) it was handed so tests can
    assert on what the model would have been allowed to see. Returns a
    scripted related_node_ids list when the test wants to exercise
    navigation."""

    def __init__(self, related_node_ids=None):
        self.views = []
        self.related_node_ids = related_node_ids or []

    def __call__(self, view, question, available_nodes=None):
        self.views.append(view)
        return {
            "explanation": {
                "direct_answer": "stub",
                "key_points": [],
                "limitations": [],
                "still_useful_for": [],
                "next_step": None,
                "related_node_ids": list(self.related_node_ids),
            },
            "used_fallback": False,
        }

    @property
    def last_view(self):
        return self.views[-1]


_UNAVAILABLE = object()


class FakeIntent:
    """A scripted stand-in for ai.interface.classify_intent(). Tests
    supply message -> ConversationIntent (or the _UNAVAILABLE sentinel,
    simulating a provider/schema failure), because a real conversation
    asks genuinely different things turn to turn -- one canned response
    can't stand in for a whole conversation the way it could for a single
    explanation call."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[SimpleNamespace] = []

    def __call__(
        self,
        message,
        valid_majors,
        current_topic_scope,
        active_options,
        stated_priority,
        selected_detail_path,
        pending_option_action=None,
        known_option_credits=None,
        pending_field_request=None,
    ):
        self.calls.append(
            SimpleNamespace(
                message=message,
                current_topic_scope=current_topic_scope,
                active_options=list(active_options),
                stated_priority=stated_priority,
                selected_detail_path=selected_detail_path,
                pending_option_action=pending_option_action,
                known_option_credits=known_option_credits,
                pending_field_request=pending_field_request,
            )
        )
        if message not in self.responses:
            raise KeyError(f"FakeIntent has no scripted response for {message!r}")
        response = self.responses[message]
        return None if response is _UNAVAILABLE else response


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


# --- setup ------------------------------------------------------------------


def test_starting_a_comparison_activates_every_major(session_and_data):
    session, _ = session_and_data
    assert session.active_options == [
        "psychology",
        "computer_science",
        "information_technology",
        "mechanical_engineering",
    ]
    assert session.current_topic_scope == BROAD
    assert session.stated_priority is None
    assert len(session.snapshot.calculated()) == 3


# --- the spec's conversation, turn by turn -----------------------------------


def test_full_conversation_keeps_who_and_what_independent(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "What are the big tradeoffs here?": ConversationIntent(topic_scope="broad"),
            "Which one costs me more?": ConversationIntent(topic_scope="financial"),
            "Okay, what's working against me?": ConversationIntent(topic_scope="unchanged"),
            "What about jobs?": ConversationIntent(topic_scope="career"),
            "Mechanical looks rough honestly": ConversationIntent(topic_scope="unchanged"),
            "Just compare CS and IT": ConversationIntent(
                topic_scope="unchanged",
                option_change="replace",
                add_options=[
                    OptionMajorInput(major="computer_science"),
                    OptionMajorInput(major="information_technology"),
                ],
            ),
            "Which one gets me out faster?": ConversationIntent(topic_scope="timeline"),
            "Actually put all four back": ConversationIntent(
                topic_scope="unchanged", option_change="restore"
            ),
        }
    )

    def ask(message):
        return handle_turn(session, message, data, classify=intent, explain=explain)

    ask("What are the big tradeoffs here?")
    assert session.current_topic_scope == BROAD
    assert len(session.active_options) == 4
    assert len(_majors_in(explain.last_view)) == 3

    ask("Which one costs me more?")
    assert session.current_topic_scope == FINANCIAL
    assert len(session.active_options) == 4
    assert len(_majors_in(explain.last_view)) == 3

    ask("Okay, what's working against me?")
    assert session.current_topic_scope == FINANCIAL
    assert session.last_question_intent == "inherited"
    assert len(session.active_options) == 4

    ask("What about jobs?")
    assert session.current_topic_scope == CAREER
    assert len(session.active_options) == 4

    ask("Mechanical looks rough honestly")
    assert len(session.active_options) == 4
    assert "mechanical_engineering" in session.active_options

    ask("Just compare CS and IT")
    assert session.active_options == [
        "psychology",
        "computer_science",
        "information_technology",
    ]
    assert session.current_topic_scope == CAREER

    ask("Which one gets me out faster?")
    assert session.current_topic_scope == TIMELINE
    assert len(session.active_options) == 3
    assert len(_majors_in(explain.last_view)) == 2

    ask("Actually put all four back")
    assert len(session.active_options) == 4
    assert session.current_topic_scope == TIMELINE


# --- the three rules, isolated ------------------------------------------------


def test_topic_change_never_touches_options(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    before = list(session.active_options)

    messages = {
        "Which one costs more?": ConversationIntent(topic_scope="financial"),
        "What about careers?": ConversationIntent(topic_scope="career"),
        "How long will each take?": ConversationIntent(topic_scope="timeline"),
        "What happens to my credits?": ConversationIntent(topic_scope="credits"),
    }
    intent = FakeIntent(messages)
    for message in messages:
        handle_turn(session, message, data, classify=intent, explain=explain)
        assert session.active_options == before


def test_option_change_never_touches_topic(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "Which one costs more?": ConversationIntent(topic_scope="financial"),
            "Drop Mechanical Engineering": ConversationIntent(
                topic_scope="unchanged",
                option_change="remove",
                remove_options=["mechanical_engineering"],
            ),
        }
    )

    handle_turn(session, "Which one costs more?", data, classify=intent, explain=explain)
    assert session.current_topic_scope == FINANCIAL

    handle_turn(session, "Drop Mechanical Engineering", data, classify=intent, explain=explain)
    assert session.current_topic_scope == FINANCIAL
    assert "mechanical_engineering" not in session.active_options


def test_priority_never_touches_options_or_topic(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "I care most about graduating quickly": ConversationIntent(
                topic_scope="unchanged", priority_update="timeline"
            ),
        }
    )
    before_options = list(session.active_options)
    before_scope = session.current_topic_scope

    # "unchanged" on the very first turn is genuinely unresolvable, so
    # seed a real scope first the same way a normal conversation would.
    session.set_topic_scope(BROAD, "explicit")
    handle_turn(
        session, "I care most about graduating quickly", data, classify=intent, explain=explain
    )

    assert session.stated_priority == "timeline"
    assert session.active_options == before_options
    assert session.current_topic_scope == BROAD


def test_preference_statements_never_narrow_the_comparison(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    before = list(session.active_options)

    messages = {
        "I'm leaning toward IT": ConversationIntent(topic_scope="broad"),
        "Computer Science sounds more interesting": ConversationIntent(topic_scope="unchanged"),
        "Psychology seems expensive": ConversationIntent(topic_scope="financial"),
        "Tell me more about Computer Science": ConversationIntent(topic_scope="unchanged"),
    }
    intent = FakeIntent(messages)
    for message in messages:
        handle_turn(session, message, data, classify=intent, explain=explain)
        assert session.active_options == before, f"{message!r} changed the options"


# --- clarification ------------------------------------------------------------


def test_ambiguous_option_instruction_changes_nothing(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "Let's just focus on those two": ConversationIntent(
                topic_scope="unchanged",
                option_change="unclear",
                needs_clarification=True,
                clarification_type="ambiguous_option_change",
            ),
        }
    )
    before = list(session.active_options)
    scope_before = session.current_topic_scope

    result = handle_turn(
        session, "Let's just focus on those two", data, classify=intent, explain=explain
    )

    assert result.needs_clarification
    assert session.active_options == before
    assert session.current_topic_scope == scope_before
    assert explain.views == []


def test_verdict_question_gets_a_redirect_not_a_ranking(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "So which one is better?": ConversationIntent(
                topic_scope="unclear",
                needs_clarification=True,
                clarification_type="verdict_without_priority",
            ),
        }
    )

    result = handle_turn(session, "So which one is better?", data, classify=intent, explain=explain)

    assert result.needs_clarification
    assert "doesn't pick a winner" in result.clarification
    assert explain.views == []


def test_ambiguous_major_lists_real_display_names(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "Add business": ConversationIntent(
                topic_scope="broad",
                needs_clarification=True,
                clarification_type="ambiguous_major",
                # Not a realistic ambiguous pair semantically, but the
                # fixture's data doesn't model a real B.A./B.S. split --
                # this only needs two real keys to prove the mechanism
                # lists actual display names rather than raw keys.
                ambiguous_candidates=["computer_science", "information_technology"],
            ),
        }
    )
    result = handle_turn(session, "Add business", data, classify=intent, explain=explain)
    assert result.needs_clarification
    assert "Computer Science" in result.clarification
    assert "Information Technology" in result.clarification


def test_first_turn_unchanged_asks_rather_than_guesses():
    """The classifier answered correctly given what it knew -- there's
    truly no prior scope on turn one. This must be a deterministic
    clarification, never ai_unavailable and never a silent default."""
    data = _reference_data()
    session = ConversationSession(session_id="test")
    inputs = MultiComparisonInputs(
        current_major="psychology",
        credits_completed=72,
        options=[ComparisonOption(major="computer_science", credits_transferable=66)],
    )
    start_comparison(session, inputs, data)
    explain = FakeExplain()
    intent = FakeIntent({"why?": ConversationIntent(topic_scope="unchanged")})

    result = handle_turn(session, "why?", data, classify=intent, explain=explain)

    assert result.needs_clarification
    assert not result.ai_unavailable
    assert explain.views == []


# --- priority -------------------------------------------------------------


def test_priority_survives_an_option_removal(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "I care most about graduating quickly": ConversationIntent(
                topic_scope="broad", priority_update="timeline"
            ),
            "Remove Business Administration": ConversationIntent(
                topic_scope="unchanged",
                option_change="remove",
                remove_options=["mechanical_engineering"],
            ),
        }
    )
    handle_turn(
        session, "I care most about graduating quickly", data, classify=intent, explain=explain
    )
    assert session.stated_priority == "timeline"

    handle_turn(session, "Remove Business Administration", data, classify=intent, explain=explain)
    assert session.stated_priority == "timeline"
    assert "mechanical_engineering" not in session.active_options


def test_priority_is_cleared_only_by_explicit_statement(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "Cost matters most to me": ConversationIntent(
                topic_scope="broad", priority_update="financial"
            ),
            "Actually never mind about that": ConversationIntent(
                topic_scope="unchanged", priority_update="cleared"
            ),
        }
    )
    handle_turn(session, "Cost matters most to me", data, classify=intent, explain=explain)
    assert session.stated_priority == "financial"

    handle_turn(session, "Actually never mind about that", data, classify=intent, explain=explain)
    assert session.stated_priority is None


def test_reaction_never_sets_a_priority(session_and_data):
    """'CS looks nice' must never be classified as a priority statement --
    this is a prompt-level rule (see INTENT_SYSTEM_PROMPT), but the state
    layer only ever writes what a validated priority_update says, so a
    classifier that got it right produces no state change either way."""
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent({"CS looks nice": ConversationIntent(topic_scope="broad")})
    handle_turn(session, "CS looks nice", data, classify=intent, explain=explain)
    assert session.stated_priority is None


def test_conflicting_priority_clarifies_and_commits_nothing(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "I care about both cost and speed": ConversationIntent(
                topic_scope="unclear",
                needs_clarification=True,
                clarification_type="conflicting_priority",
            ),
        }
    )
    result = handle_turn(
        session, "I care about both cost and speed", data, classify=intent, explain=explain
    )
    assert result.needs_clarification
    assert session.stated_priority is None


def test_verdict_with_an_existing_priority_does_not_need_clarification(session_and_data):
    """Once a priority is on record, a later verdict question resolves to
    that priority's topic scope instead of asking again -- Fork anchors
    the answer to what the student already said, using deterministic
    facts for that one dimension, rather than inventing a ranking."""
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "I care most about graduating quickly": ConversationIntent(
                topic_scope="broad", priority_update="timeline"
            ),
            "Okay, which is best for me then?": ConversationIntent(topic_scope="timeline"),
        }
    )
    handle_turn(
        session, "I care most about graduating quickly", data, classify=intent, explain=explain
    )
    result = handle_turn(
        session, "Okay, which is best for me then?", data, classify=intent, explain=explain
    )
    assert not result.needs_clarification
    assert session.current_topic_scope == TIMELINE


# --- pending options (already known, just missing a field) ------------------


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
    intent = FakeIntent({"Compare these": ConversationIntent(topic_scope="broad")})

    handle_turn(session, "Compare these", data, classify=intent, explain=explain)

    view_majors = _majors_in(explain.last_view)
    assert "Mechanical Engineering" in view_majors
    pending = [o for o in explain.last_view["options"] if o["status"] == "pending"][0]
    assert "data" not in pending
    assert pending["missing_fields"] == ["credits_transferable"]


# --- conversational "add", including a genuinely new major ------------------


def test_adding_a_genuinely_new_major_with_credits_calculates_immediately(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "Add Business Administration; 50 credits apply": ConversationIntent(
                topic_scope="broad",  # first turn in this session -- nothing to inherit yet
                option_change="add",
                add_options=[OptionMajorInput(major="business_administration", credits_transferable=50)],
            ),
        }
    )
    result = handle_turn(
        session,
        "Add Business Administration; 50 credits apply",
        data,
        classify=intent,
        explain=explain,
    )

    assert not result.needs_clarification
    assert "business_administration" in session.active_options
    outcome = session.snapshot.outcome_for("business_administration")
    assert outcome is not None
    assert outcome.status == "calculated"
    # The explanation model WAS called this turn -- a complete add with a
    # real answer to give isn't a short-circuit.
    assert explain.views != []


def test_adding_a_new_major_without_credits_asks_directly_and_skips_explanation(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "Add Business Administration": ConversationIntent(
                topic_scope="broad",  # first turn in this session -- nothing to inherit yet
                option_change="add",
                add_options=[OptionMajorInput(major="business_administration", credits_transferable=None)],
            ),
        }
    )
    result = handle_turn(
        session, "Add Business Administration", data, classify=intent, explain=explain
    )

    assert not result.needs_clarification
    assert "Business Administration" in result.explanation["direct_answer"]
    assert "72" in result.explanation["direct_answer"]  # credits_completed, named directly
    assert session.pending_field_request is not None
    assert session.pending_field_request.major == "business_administration"
    # The short-circuit never called the explanation model -- there's
    # nothing to explain yet.
    assert explain.views == []
    # But the option IS already part of the comparison, pending.
    outcome = session.snapshot.outcome_for("business_administration")
    assert outcome is not None
    assert outcome.status == "pending"


def test_bare_number_reply_resolves_the_pending_field_without_a_second_ai_call(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            # "broad" is a freshly-stated scope (not "unchanged"), so this
            # counts as a real analysis question worth resuming -- see the
            # companion test below for the "nothing to resume" case.
            "Add Business Administration": ConversationIntent(
                topic_scope="broad",
                option_change="add",
                add_options=[OptionMajorInput(major="business_administration", credits_transferable=None)],
            ),
        }
    )
    handle_turn(session, "Add Business Administration", data, classify=intent, explain=explain)
    assert len(intent.calls) == 1
    assert session.pending_analysis_question is not None

    result = handle_turn(session, "50", data, classify=intent, explain=explain)

    # The bare-number reply never reached the classifier -- resolved by
    # regex, exactly the point of the short-circuit.
    assert len(intent.calls) == 1
    assert session.pending_field_request is None
    assert session.pending_analysis_question is None
    outcome = session.snapshot.outcome_for("business_administration")
    assert outcome.status == "calculated"
    # Resumed straight into a real explanation rather than a bare
    # confirmation -- FakeExplain's stub answer proves explain() actually
    # ran, using the option that's now calculated.
    assert result.explanation["direct_answer"] == "stub"


def test_bare_add_with_no_fresh_topic_gets_a_bare_confirmation_not_a_resume(session_and_data):
    """A bare 'Add X' with topic_scope='unchanged' (nothing asked about
    topic) must NOT be treated as a resumable analysis question -- there
    is nothing to resume. Needs a real prior turn first so 'unchanged' has
    something to inherit rather than tripping the first-turn clarification."""
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "Which one costs more?": ConversationIntent(topic_scope="financial"),
            "Add Business Administration": ConversationIntent(
                topic_scope="unchanged",
                option_change="add",
                add_options=[OptionMajorInput(major="business_administration", credits_transferable=None)],
            ),
        }
    )
    handle_turn(session, "Which one costs more?", data, classify=intent, explain=explain)
    handle_turn(session, "Add Business Administration", data, classify=intent, explain=explain)
    assert session.pending_analysis_question is None

    result = handle_turn(session, "50", data, classify=intent, explain=explain)

    assert session.pending_field_request is None
    assert "Business Administration" in result.explanation["direct_answer"]
    assert "is now included" in result.explanation["direct_answer"]


def test_max_options_rejected_with_a_clarification_not_a_crash(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    assert len(session.inputs.options) == 3 < MAX_OPTIONS

    intent = FakeIntent(
        {
            "Add Business Administration": ConversationIntent(
                topic_scope="broad", option_change="add",
                add_options=[OptionMajorInput(major="business_administration", credits_transferable=50)],
            ),
            "Add Biology": ConversationIntent(
                topic_scope="unchanged", option_change="add",
                add_options=[OptionMajorInput(major="biology", credits_transferable=50)],
            ),
        }
    )
    # Fills the comparison to exactly MAX_OPTIONS (3 existing + this 1 new
    # one = 4), then a second, genuinely different new major should be
    # rejected rather than silently exceeding the cap.
    handle_turn(session, "Add Business Administration", data, classify=intent, explain=explain)
    assert len(session.inputs.options) == MAX_OPTIONS

    before_options = list(session.inputs.options)
    result = handle_turn(session, "Add Biology", data, classify=intent, explain=explain)

    assert result.needs_clarification
    assert str(MAX_OPTIONS) in result.clarification
    assert session.inputs.options == before_options


# --- targeted replace (regressions from a real conversational test) --------
#
# Scenario: anchor Mechanical & Energy Engineering, four active
# alternatives (IT, Business, CS, Psych BA) -- already at MAX_OPTIONS.
# "Replace Psychology B.A. with Psychology B.S., keep IT/Business/CS."


@pytest.fixture
def four_option_session():
    data = _reference_data()
    session = ConversationSession(session_id="targeted-replace")
    inputs = MultiComparisonInputs(
        current_major="mechanical_engineering",
        credits_completed=90,
        options=[
            ComparisonOption(major="information_technology", credits_transferable=70),
            ComparisonOption(major="business_administration", credits_transferable=75),
            ComparisonOption(major="computer_science", credits_transferable=65),
            ComparisonOption(major="psychology_ba", credits_transferable=84),
        ],
    )
    start_comparison(session, inputs, data)
    assert len(session.inputs.options) == MAX_OPTIONS
    return session, data


def test_targeted_replace_at_max_options_is_atomic_not_add_then_reject(four_option_session):
    """The core regression: replacing ONE of four alternatives must stay
    at four. Applying it as add-then-validate (briefly five) before
    removing the old one would spuriously trip MAX_OPTIONS even though
    the net change is a like-for-like swap."""
    session, data = four_option_session
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "replace Psych BA with Psych BS, keep IT/Business/CS": ConversationIntent(
                topic_scope="timeline",
                option_change="replace",
                remove_options=["psychology_ba"],
                add_options=[OptionMajorInput(major="psychology_bs", credits_transferable=84)],
            ),
        }
    )

    result = handle_turn(
        session,
        "replace Psych BA with Psych BS, keep IT/Business/CS",
        data,
        classify=intent,
        explain=explain,
    )

    assert not result.needs_clarification
    assert len(session.inputs.options) == MAX_OPTIONS
    known = {o.major for o in session.inputs.options}
    assert known == {
        "information_technology", "business_administration",
        "computer_science", "psychology_bs",
    }
    assert "psychology_ba" not in known
    assert session.active_options == [
        "mechanical_engineering", "information_technology",
        "business_administration", "computer_science", "psychology_bs",
    ]
    # The explicit "keep" instruction is honored -- nothing else dropped.
    for major in ("information_technology", "business_administration", "computer_science"):
        assert major in session.active_options


def test_targeted_replace_keeps_the_84_credits_and_reuses_them_for_the_new_major(
    four_option_session,
):
    session, data = four_option_session
    intent = FakeIntent(
        {
            "swap psych": ConversationIntent(
                topic_scope="unchanged",
                option_change="replace",
                remove_options=["psychology_ba"],
                add_options=[OptionMajorInput(major="psychology_bs", credits_transferable=84)],
            ),
        }
    )
    handle_turn(session, "swap psych", data, classify=intent, explain=FakeExplain())
    new_option = session.inputs.option_for("psychology_bs")
    assert new_option.credits_transferable == 84


def test_failed_targeted_replace_preserves_the_old_trusted_state(four_option_session):
    """If the net change would still exceed MAX_OPTIONS (e.g. one major
    replaced by two), the whole mutation must be rejected -- the old
    comparison (including Psychology B.A.'s 84 credits) must still be
    exactly as it was, not partially applied."""
    session, data = four_option_session
    before_options = list(session.inputs.options)
    before_active = list(session.active_options)
    intent = FakeIntent(
        {
            "replace psych with two new majors": ConversationIntent(
                topic_scope="unchanged",
                option_change="replace",
                remove_options=["psychology_ba"],
                add_options=[
                    OptionMajorInput(major="psychology_bs", credits_transferable=84),
                    OptionMajorInput(major="biology", credits_transferable=50),
                ],
            ),
        }
    )

    result = handle_turn(
        session, "replace psych with two new majors", data, classify=intent, explain=FakeExplain()
    )

    assert result.needs_clarification
    assert session.inputs.options == before_options
    assert session.active_options == before_active
    assert session.inputs.option_for("psychology_ba").credits_transferable == 84
    # A follow-up should be able to complete the attempted swap --
    # whatever was understood about it survives the failure.
    assert session.pending_option_action is not None
    assert session.pending_option_action.action == "replace"
    assert session.pending_option_action.remove_majors == ["psychology_ba"]


def test_ambiguous_replace_asks_what_to_replace_it_with_not_what_to_add(four_option_session):
    """'Replace Psych BA' with no target major named must produce a
    replace-specific clarification, and must NOT be phrased as an add
    question. This is the structural bug behind 'can you replace it' ->
    'Which major should I add?'."""
    session, data = four_option_session
    intent = FakeIntent(
        {
            "replace psych ba": ConversationIntent(
                topic_scope="unchanged",
                option_change="replace",
                remove_options=["psychology_ba"],
                needs_clarification=True,
                clarification_type="ambiguous_option_change",
            ),
        }
    )

    result = handle_turn(session, "replace psych ba", data, classify=intent, explain=FakeExplain())

    assert result.needs_clarification
    assert "replace Psychology (B.A.) with" in result.clarification
    assert "should I add" not in result.clarification.lower()
    assert session.pending_option_action is not None
    assert session.pending_option_action.action == "replace"
    assert session.pending_option_action.remove_majors == ["psychology_ba"]


def test_pending_option_action_is_passed_to_the_classifier_on_the_next_turn(
    four_option_session,
):
    """The follow-up turn must actually receive the pending context --
    otherwise the classifier has no way to know a replace is in flight."""
    session, data = four_option_session
    intent = FakeIntent(
        {
            "replace psych ba": ConversationIntent(
                topic_scope="unchanged",
                option_change="replace",
                remove_options=["psychology_ba"],
                needs_clarification=True,
                clarification_type="ambiguous_option_change",
            ),
            "psychology bs": ConversationIntent(
                topic_scope="unchanged",
                option_change="replace",
                remove_options=["psychology_ba"],
                add_options=[OptionMajorInput(major="psychology_bs", credits_transferable=84)],
            ),
        }
    )

    handle_turn(session, "replace psych ba", data, classify=intent, explain=FakeExplain())
    assert intent.calls[-1].pending_option_action is None  # nothing pending yet on THIS call

    result = handle_turn(session, "psychology bs", data, classify=intent, explain=FakeExplain())

    # The second call carried the first turn's unresolved action as context.
    assert intent.calls[-1].pending_option_action == {
        "action": "replace",
        "remove_majors": ["psychology_ba"],
        "add_majors": [],
    }
    # And, since the scripted response for this turn completes the swap,
    # it actually applied and cleared the pending state.
    assert not result.needs_clarification
    assert session.pending_option_action is None
    assert "psychology_bs" in {o.major for o in session.inputs.options}


def test_known_option_credits_are_offered_to_the_classifier(four_option_session):
    """Lets an explicit 'same credits transfer over' resolve
    deterministically -- the classifier is given what Fork already knows,
    rather than being asked to remember or invent a number."""
    session, data = four_option_session
    intent = FakeIntent(
        {"anything": ConversationIntent(topic_scope="broad")},
    )
    handle_turn(session, "anything", data, classify=intent, explain=FakeExplain())
    assert intent.calls[-1].known_option_credits == {
        "information_technology": 70,
        "business_administration": 75,
        "computer_science": 65,
        "psychology_ba": 84,
    }


# --- split clarification: mutation applies, analysis-only asks alongside it -


def test_apply_and_clarify_combined_response(four_option_session):
    """'Replace Psych BA with Psych BS, then tell me which is best
    overall' -- the mutation is clear, the analysis is ambiguous. The
    mutation must still apply, and the response combines a confirmation
    with the analysis clarification, never silently discarding a valid
    instruction just because part of the same message came back
    ambiguous."""
    session, data = four_option_session
    message = "replace psych ba with psych bs, which is best overall?"
    intent = FakeIntent(
        {
            message: ConversationIntent(
                topic_scope="unclear",
                option_change="replace",
                remove_options=["psychology_ba"],
                add_options=[OptionMajorInput(major="psychology_bs", credits_transferable=84)],
                needs_clarification=True,
                clarification_type="verdict_without_priority",
            ),
        }
    )

    result = handle_turn(session, message, data, classify=intent, explain=FakeExplain())

    assert result.needs_clarification
    # The mutation actually applied...
    assert "psychology_bs" in session.active_options
    assert "psychology_ba" not in session.active_options
    # ...and the response confirms that AND asks the analysis question,
    # rather than silently applying the swap and only showing the
    # clarification (which would look like the replace was ignored).
    assert "You're now comparing Psychology (B.S.) instead of Psychology (B.A.)." in result.clarification
    assert "doesn't pick a winner" in result.clarification


def test_ambiguous_major_still_blocks_the_mutation_unlike_analysis_only(four_option_session):
    """Contrast case for the test above: 'Replace Psychology with CS' when
    Psychology itself is ambiguous (BA vs BS) must NOT apply anything --
    ambiguous_major is about resolving WHO, not the analysis, so it keeps
    blocking exactly as before."""
    session, data = four_option_session
    message = "replace psychology with computer science"
    intent = FakeIntent(
        {
            message: ConversationIntent(
                topic_scope="unchanged",
                option_change="replace",
                needs_clarification=True,
                clarification_type="ambiguous_major",
                ambiguous_candidates=["psychology_ba", "psychology_bs"],
            ),
        }
    )
    before = list(session.active_options)

    result = handle_turn(session, message, data, classify=intent, explain=FakeExplain())

    assert result.needs_clarification
    assert session.active_options == before
    assert "Psychology (B.A.)" in result.clarification
    assert "Psychology (B.S.)" in result.clarification


def test_full_acceptance_scenario_replace_missing_field_then_auto_resume_timeline(
    four_option_session,
):
    """The exact compound-question acceptance test: a targeted replace
    (keeping the other three), a timeline question attached, and the new
    major's transfer credits unknown -> Fork asks for them. The student
    answers "86" -> validated, recalculated, and the ORIGINAL timeline
    question is answered automatically -- never repeated back to the
    student."""
    session, data = four_option_session
    explain = FakeExplain()
    message = (
        "replace psych ba with psych bs, keep it/business/cs, which is fastest?"
    )
    intent = FakeIntent(
        {
            message: ConversationIntent(
                topic_scope="timeline",
                option_change="replace",
                remove_options=["psychology_ba"],
                add_options=[OptionMajorInput(major="psychology_bs", credits_transferable=None)],
            ),
        }
    )

    result = handle_turn(session, message, data, classify=intent, explain=explain)

    # Missing-field ask this turn -- not a real answer yet.
    assert not result.needs_clarification
    assert "Psychology (B.S.)" in result.explanation["direct_answer"]
    assert "how many" in result.explanation["direct_answer"].lower()
    assert session.active_options == [
        "mechanical_engineering", "information_technology",
        "business_administration", "computer_science", "psychology_bs",
    ]
    assert session.pending_field_request is not None
    assert session.pending_analysis_question is not None
    assert session.pending_analysis_question.topic_scope == "timeline"
    assert explain.views == []  # no explanation call yet -- nothing to resume from
    assert len(intent.calls) == 1

    # Student answers -- bare-number fast path, no second AI call.
    result2 = handle_turn(session, "86", data, classify=intent, explain=explain)

    assert not result2.needs_clarification
    assert len(intent.calls) == 1  # still just the one classification call
    assert session.pending_field_request is None
    assert session.pending_analysis_question is None
    outcome = session.snapshot.outcome_for("psychology_bs")
    assert outcome.status == "calculated"
    # The original "which is fastest" question was auto-answered.
    assert explain.views != []
    assert explain.last_view["topic_scope"] == "timeline"


# --- pending-state lifetime: discard only when genuinely unrelated ---------


def test_pending_field_request_resolves_via_classifier_for_non_bare_number_replies(
    session_and_data,
):
    """'86 credits apply' and 'I think 86 apply' already match the
    bare-number fast path. This covers a reply that does NOT (a spelled-
    out number, no digits at all) -- the classifier gets a real chance to
    resolve it via pending_field_value instead of the pending state being
    discarded outright."""
    session, data = session_and_data
    intent = FakeIntent(
        {
            "Add Business Administration": ConversationIntent(
                topic_scope="broad",
                option_change="add",
                add_options=[OptionMajorInput(major="business_administration", credits_transferable=None)],
            ),
            "the credits that apply are sixty": ConversationIntent(
                topic_scope="unchanged", pending_field_value=60
            ),
        }
    )
    handle_turn(session, "Add Business Administration", data, classify=intent, explain=FakeExplain())
    assert session.pending_field_request is not None

    handle_turn(
        session, "the credits that apply are sixty", data, classify=intent, explain=FakeExplain()
    )

    assert session.pending_field_request is None
    outcome = session.snapshot.outcome_for("business_administration")
    assert outcome.status == "calculated"
    assert session.inputs.option_for("business_administration").credits_transferable == 60


def test_pending_field_request_cleared_when_the_next_turn_is_genuinely_unrelated(
    session_and_data,
):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent(
        {
            "Add Business Administration": ConversationIntent(
                topic_scope="broad",
                option_change="add",
                add_options=[OptionMajorInput(major="business_administration", credits_transferable=None)],
            ),
            "What does salary look like instead?": ConversationIntent(
                topic_scope="career", pending_field_value=None
            ),
        }
    )
    handle_turn(session, "Add Business Administration", data, classify=intent, explain=explain)
    assert session.pending_field_request is not None
    assert session.pending_analysis_question is not None

    result = handle_turn(
        session, "What does salary look like instead?", data, classify=intent, explain=explain
    )

    assert session.pending_field_request is None
    assert session.pending_analysis_question is None
    assert session.current_topic_scope == "career"
    assert not result.needs_clarification


def test_pending_option_action_cleared_when_the_next_turn_is_genuinely_unrelated(
    four_option_session,
):
    session, data = four_option_session
    intent = FakeIntent(
        {
            "replace psych ba": ConversationIntent(
                topic_scope="unchanged",
                option_change="replace",
                remove_options=["psychology_ba"],
                needs_clarification=True,
                clarification_type="ambiguous_option_change",
            ),
            "what's the tuition for CS?": ConversationIntent(topic_scope="financial"),
        }
    )
    handle_turn(session, "replace psych ba", data, classify=intent, explain=FakeExplain())
    assert session.pending_option_action is not None

    handle_turn(session, "what's the tuition for CS?", data, classify=intent, explain=FakeExplain())

    assert session.pending_option_action is None


# --- restore semantics: named restores one, unnamed restores all -----------


def test_named_restore_reactivates_just_that_major(session_and_data):
    session, data = session_and_data
    intent = FakeIntent(
        {
            "Drop Mechanical Engineering": ConversationIntent(
                topic_scope="unchanged",
                option_change="remove",
                remove_options=["mechanical_engineering"],
            ),
            "Drop IT too": ConversationIntent(
                topic_scope="unchanged",
                option_change="remove",
                remove_options=["information_technology"],
            ),
            "Actually put Mechanical Engineering back": ConversationIntent(
                topic_scope="unchanged",
                option_change="restore",
                add_options=[OptionMajorInput(major="mechanical_engineering")],
            ),
        }
    )
    handle_turn(session, "Drop Mechanical Engineering", data, classify=intent, explain=FakeExplain())
    handle_turn(session, "Drop IT too", data, classify=intent, explain=FakeExplain())
    assert "mechanical_engineering" not in session.active_options
    assert "information_technology" not in session.active_options

    handle_turn(
        session, "Actually put Mechanical Engineering back", data, classify=intent, explain=FakeExplain()
    )

    assert "mechanical_engineering" in session.active_options
    # The OTHER dropped major stays inactive -- naming one doesn't
    # restore everyone.
    assert "information_technology" not in session.active_options


# --- trusted state vs conversation state -------------------------------------


def test_no_ai_output_is_ever_stored_on_the_session(session_and_data):
    session, data = session_and_data
    intent = FakeIntent({"Which one costs more?": ConversationIntent(topic_scope="financial")})
    handle_turn(session, "Which one costs more?", data, classify=intent, explain=FakeExplain())

    turn = session.turns[-1]
    stored = set(turn.__dict__)
    assert stored == {"text", "topic_scope", "question_intent", "referenced_options"}
    assert turn.text == "Which one costs more?"


def test_snapshot_rebuilds_when_inputs_change(session_and_data):
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
    intent = FakeIntent(
        {
            "Which one costs more?": ConversationIntent(topic_scope="financial"),
            "What about careers?": ConversationIntent(topic_scope="career"),
        }
    )
    first = session.snapshot

    handle_turn(session, "Which one costs more?", data, classify=intent, explain=explain)
    handle_turn(session, "What about careers?", data, classify=intent, explain=explain)

    assert session.snapshot is first


# --- AI failure ---------------------------------------------------------------


def test_ai_unavailable_touches_no_state(session_and_data):
    session, data = session_and_data
    explain = FakeExplain()
    intent = FakeIntent({"Which one costs more?": _UNAVAILABLE})

    before_options = list(session.active_options)
    before_scope = session.current_topic_scope
    before_priority = session.stated_priority

    result = handle_turn(session, "Which one costs more?", data, classify=intent, explain=explain)

    assert result.ai_unavailable
    assert not result.needs_clarification
    assert session.active_options == before_options
    assert session.current_topic_scope == before_scope
    assert session.stated_priority == before_priority
    assert explain.views == []


# --- navigation: pills and auto-focus ----------------------------------------


def test_one_node_one_referenced_major_auto_focuses_and_switches_path(session_and_data):
    session, data = session_and_data
    explain = FakeExplain(related_node_ids=["financial"])
    intent = FakeIntent(
        {
            "Show me CS's financial impact": ConversationIntent(
                topic_scope="financial", referenced_majors=["computer_science"]
            ),
        }
    )
    result = handle_turn(
        session, "Show me CS's financial impact", data, classify=intent, explain=explain
    )
    assert result.navigation_target == {"major": "computer_science", "node_id": "financial"}
    assert result.navigation_pills == [{"major": "computer_science", "node_id": "financial"}]


def test_one_node_no_referenced_major_auto_focuses_current_path_only(session_and_data):
    session, data = session_and_data
    explain = FakeExplain(related_node_ids=["financial"])
    intent = FakeIntent(
        {"Why is switching costing me more?": ConversationIntent(topic_scope="financial")}
    )
    result = handle_turn(
        session,
        "Why is switching costing me more?",
        data,
        selected_detail_path="information_technology",
        classify=intent,
        explain=explain,
    )
    assert result.navigation_target == {"major": None, "node_id": "financial"}


def test_one_node_multiple_majors_produces_path_aware_pills_no_auto_focus(session_and_data):
    session, data = session_and_data
    explain = FakeExplain(related_node_ids=["salary_outlook"])
    intent = FakeIntent(
        {
            "How do CS and IT compare on salary?": ConversationIntent(
                topic_scope="career",
                referenced_majors=["computer_science", "information_technology"],
            ),
        }
    )
    result = handle_turn(
        session, "How do CS and IT compare on salary?", data, classify=intent, explain=explain
    )
    assert result.navigation_target is None
    assert result.navigation_pills == [
        {"major": "computer_science", "node_id": "salary_outlook"},
        {"major": "information_technology", "node_id": "salary_outlook"},
    ]


def test_multiple_nodes_one_major_produces_node_only_pills_with_known_path(session_and_data):
    session, data = session_and_data
    explain = FakeExplain(related_node_ids=["career", "salary_outlook", "job_market"])
    intent = FakeIntent(
        {
            "Show me IT's job demand": ConversationIntent(
                topic_scope="career", referenced_majors=["information_technology"]
            ),
        }
    )
    result = handle_turn(
        session, "Show me IT's job demand", data, classify=intent, explain=explain
    )
    assert result.navigation_target is None  # more than one node -- no arbitrary pick
    assert len(result.navigation_pills) == 3
    assert all(p["major"] == "information_technology" for p in result.navigation_pills)


def test_multiple_nodes_multiple_majors_falls_back_to_flat_pills_no_matrix(session_and_data):
    """The regression this rule exists for: a broad four-major CAREER
    answer must not produce a 3x4 matrix of pills."""
    session, data = session_and_data
    explain = FakeExplain(related_node_ids=["career", "salary_outlook", "job_market"])
    intent = FakeIntent(
        {"Which one has the best career outlook?": ConversationIntent(topic_scope="career")}
    )
    result = handle_turn(
        session, "Which one has the best career outlook?", data, classify=intent, explain=explain
    )
    assert result.navigation_target is None
    assert len(result.navigation_pills) == 3  # not 3 nodes x 3 calculated majors = 9
    assert all(p["major"] is None for p in result.navigation_pills)


def test_navigation_never_changes_active_options_or_topic_scope(session_and_data):
    session, data = session_and_data
    explain = FakeExplain(related_node_ids=["financial"])
    intent = FakeIntent(
        {
            "Show me CS's financial impact": ConversationIntent(
                topic_scope="financial", referenced_majors=["computer_science"]
            ),
        }
    )
    before_options = list(session.active_options)
    handle_turn(session, "Show me CS's financial impact", data, classify=intent, explain=explain)
    # navigation_target names a different path than whatever was
    # "selected" server-side (there IS no server-held selected path --
    # see the module's own state-boundary rule), but active_options is
    # completely untouched regardless.
    assert session.active_options == before_options


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


# =============================================================================
# Compare One (pairwise) turns
# =============================================================================


_PAIRWISE_MAJORS = {
    "information_technology": "Information Technology",
    "computer_science": "Computer Science",
    "mechanical_engineering": "Mechanical Engineering",
}


def test_pairwise_replace_with_credits_applies_immediately():
    session = ConversationSession(session_id="pairwise")
    intent = FakeIntent(
        {
            "Switch to Computer Science; 61 credits apply.": ConversationIntent(
                topic_scope="unchanged",
                option_change="replace",
                add_options=[OptionMajorInput(major="computer_science", credits_transferable=61)],
            ),
        }
    )
    result = handle_pairwise_turn(
        session,
        "Switch to Computer Science; 61 credits apply.",
        current_major="mechanical_engineering",
        prospective_major="information_technology",
        credits_completed=72,
        valid_majors=_PAIRWISE_MAJORS,
        classify=intent,
    )
    assert result.applied_option_change == {
        "major": "computer_science",
        "credits_transferable": 61,
    }
    assert result.short_circuit_explanation is None
    assert session.pending_field_request is None


def test_pairwise_replace_without_credits_never_reuses_the_previous_majors_figure():
    """The explicitly requested regression test: Mechanical -> IT at 58
    transferable credits, then "compare me to Computer Science instead"
    with no credits stated. The old major's 58 must never appear
    associated with Computer Science anywhere, and nothing gets
    calculated against CS until a real transfer figure for CS specifically
    is supplied."""
    session = ConversationSession(session_id="pairwise")
    intent = FakeIntent(
        {
            "Compare me to Computer Science instead.": ConversationIntent(
                topic_scope="unchanged",
                option_change="replace",
                add_options=[OptionMajorInput(major="computer_science", credits_transferable=None)],
            ),
        }
    )
    # The request that carries this message still has the OLD major's
    # transfer figure sitting in it (58, for information_technology) --
    # exactly the trap: credits_completed is a real, reusable fact, but
    # 58 is IT-specific and must never leak onto Computer Science.
    result = handle_pairwise_turn(
        session,
        "Compare me to Computer Science instead.",
        current_major="mechanical_engineering",
        prospective_major="information_technology",
        credits_completed=72,
        valid_majors=_PAIRWISE_MAJORS,
        classify=intent,
    )

    assert result.applied_option_change is None
    assert result.short_circuit_explanation is not None
    text = result.short_circuit_explanation["direct_answer"]
    assert "58" not in text
    assert "Computer Science" in text
    assert session.pending_field_request is not None
    assert session.pending_field_request.major == "computer_science"

    # The bare-number follow-up supplies CS's own figure -- and only then
    # does an applied_option_change appear, carrying that number, never 58.
    follow_up = handle_pairwise_turn(
        session,
        "61",
        current_major="mechanical_engineering",
        prospective_major="information_technology",
        credits_completed=72,
        valid_majors=_PAIRWISE_MAJORS,
        classify=intent,
    )
    assert follow_up.applied_option_change == {
        "major": "computer_science",
        "credits_transferable": 61,
    }
    assert follow_up.applied_option_change["credits_transferable"] != 58


def test_pairwise_add_remove_restore_get_a_redirect_not_a_crash():
    session = ConversationSession(session_id="pairwise")
    intent = FakeIntent(
        {"Add Business Administration": ConversationIntent(topic_scope="unchanged", option_change="add")}
    )
    result = handle_pairwise_turn(
        session,
        "Add Business Administration",
        current_major="mechanical_engineering",
        prospective_major="information_technology",
        credits_completed=72,
        valid_majors=_PAIRWISE_MAJORS,
        classify=intent,
    )
    assert result.needs_clarification
    assert "Compare Multiple" in result.clarification


def test_pairwise_ai_unavailable_touches_no_state():
    session = ConversationSession(session_id="pairwise")
    intent = FakeIntent({"Why does this cost more?": _UNAVAILABLE})
    result = handle_pairwise_turn(
        session,
        "Why does this cost more?",
        current_major="mechanical_engineering",
        prospective_major="information_technology",
        credits_completed=72,
        valid_majors=_PAIRWISE_MAJORS,
        classify=intent,
    )
    assert result.ai_unavailable
    assert session.stated_priority is None
    assert session.pending_field_request is None


def test_pairwise_navigation_has_no_major_label():
    """Compare One only ever has one path, so its pills never carry a
    major -- there's nothing to disambiguate."""
    pills, target = compute_pairwise_navigation(["financial", "salary_outlook"])
    assert all(p["major"] is None for p in pills)
    assert target is None  # more than one node
    pills, target = compute_pairwise_navigation(["financial"])
    assert target == {"major": None, "node_id": "financial"}
