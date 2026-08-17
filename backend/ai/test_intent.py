"""
Tests for the intent classifier: the one place natural-language
UNDERSTANDING happens for Ask Fork now, replacing three separate keyword
tables (conversation/router.py's old _TOPIC_KEYWORDS, conversation/
option_intent.py's old marker tuples, and this file's own old
_QUESTION_FOCUS).

Everything here mocks `_call_model` -- no live network call, no API key
needed. The behavior under test is the validation/retry/failure contract:
what classify_intent() returns is always either a schema-valid,
majors-validated ConversationIntent, or None (meaning "unavailable" --
see conversation/orchestrator.py for how callers must treat that).
"""

import json
from unittest.mock import patch

from ai.interface import ConversationIntent, classify_intent

_VALID_MAJORS = {
    "computer_science": "Computer Science",
    "information_technology": "Information Technology",
    "psychology_ba": "Psychology (B.A.)",
    "psychology_bs": "Psychology (B.S.)",
}


def _classify(message="What's the financial impact?", known_option_credits=None, pending_field_request=None):
    return classify_intent(
        message,
        _VALID_MAJORS,
        current_topic_scope=None,
        active_options=["psychology_ba", "computer_science"],
        stated_priority=None,
        selected_detail_path=None,
        known_option_credits=known_option_credits,
        pending_field_request=pending_field_request,
    )


def _good(**overrides):
    body = {
        "topic_scope": "financial",
        "option_change": "none",
        "referenced_majors": [],
        "add_options": [],
        "remove_options": [],
        "priority_update": None,
        "pending_field_value": None,
        "needs_clarification": False,
        "clarification_type": None,
        "ambiguous_candidates": [],
    }
    body.update(overrides)
    return json.dumps(body)


# --- happy path ---------------------------------------------------------


def test_valid_response_is_parsed_into_a_conversation_intent():
    with patch("ai.interface._call_model", return_value=_good()):
        intent = _classify()
    assert isinstance(intent, ConversationIntent)
    assert intent.topic_scope == "financial"


def test_uses_the_intent_model_not_the_explanation_model():
    """INTENT_MODEL and EXPLANATION_MODEL are kept as separate names so
    they could diverge later without an architectural change -- this
    locks in that classify_intent() actually passes it through."""
    from ai.interface import INTENT_MODEL

    with patch("ai.interface._call_model", return_value=_good()) as mock_call:
        _classify()
    assert mock_call.call_args.kwargs.get("model") == INTENT_MODEL


# --- major-key validation: nothing the model names is trusted raw -------


def test_invented_major_key_is_dropped():
    with patch(
        "ai.interface._call_model",
        return_value=_good(referenced_majors=["computer_science", "underwater_basket_weaving"]),
    ):
        intent = _classify()
    assert intent.referenced_majors == ["computer_science"]


def test_add_options_with_an_invalid_major_are_dropped():
    with patch(
        "ai.interface._call_model",
        return_value=_good(
            option_change="add",
            add_options=[
                {"major": "computer_science", "credits_transferable": 61},
                {"major": "not_a_real_major", "credits_transferable": 10},
            ],
        ),
    ):
        intent = _classify()
    assert [o.major for o in intent.add_options] == ["computer_science"]


def test_option_change_with_nothing_valid_left_forces_clarification():
    """If validation strips every named major out of an add/remove/replace,
    there's nothing left to act on -- this must never silently become
    ACTION_NONE (which would look like the instruction was ignored) or
    silently proceed with an empty change."""
    with patch(
        "ai.interface._call_model",
        return_value=_good(
            option_change="add",
            add_options=[{"major": "not_a_real_major", "credits_transferable": 10}],
        ),
    ):
        intent = _classify()
    assert intent.needs_clarification
    assert intent.clarification_type == "ambiguous_option_change"


def test_ambiguous_candidates_are_also_validated():
    with patch(
        "ai.interface._call_model",
        return_value=_good(
            needs_clarification=True,
            clarification_type="ambiguous_major",
            ambiguous_candidates=["psychology_ba", "psychology_bs", "not_real"],
        ),
    ):
        intent = _classify()
    assert set(intent.ambiguous_candidates) == {"psychology_ba", "psychology_bs"}


# --- reuse_credits_from: the model names a major, code does the lookup --
#
# Trust boundary: "the same credits transfer over" must never result in
# the MODEL's own copy of a number reaching a calculation, even when that
# number is visibly correct in known_option_credits. The model is only
# ever trusted to say WHICH major to copy from; the actual figure has to
# come from code's own lookup against known_option_credits, so a
# transposition or copy error in the model's output can never produce a
# wrong number downstream -- there's no code path that reads the model's
# own digits for this at all.


def test_reuse_credits_from_is_resolved_by_code_lookup_not_the_models_number():
    with patch(
        "ai.interface._call_model",
        return_value=_good(
            option_change="add",
            add_options=[
                {
                    "major": "psychology_bs",
                    "credits_transferable": None,
                    "reuse_credits_from": "psychology_ba",
                }
            ],
        ),
    ):
        intent = _classify(known_option_credits={"psychology_ba": 84})
    assert intent.add_options[0].credits_transferable == 84
    assert intent.add_options[0].reuse_credits_from is None  # consumed once resolved


def test_a_number_the_model_wrote_alongside_reuse_credits_from_is_discarded():
    """Even if the model ALSO wrote a number (correct or not) next to
    reuse_credits_from, code's lookup wins outright -- the model's own
    digits are never trusted for this, not even as a fallback or a
    cross-check."""
    with patch(
        "ai.interface._call_model",
        return_value=_good(
            option_change="add",
            add_options=[
                {
                    "major": "psychology_bs",
                    "credits_transferable": 999,  # the model's own number -- must be ignored
                    "reuse_credits_from": "psychology_ba",
                }
            ],
        ),
    ):
        intent = _classify(known_option_credits={"psychology_ba": 84})
    assert intent.add_options[0].credits_transferable == 84
    assert intent.add_options[0].credits_transferable != 999


def test_reuse_credits_from_naming_an_unknown_major_resolves_to_none_not_a_guess():
    """If the model names a major with no known figure (or an invalid
    one), the result is null -- never a fabricated number, and never the
    model's own credits_transferable as a fallback."""
    with patch(
        "ai.interface._call_model",
        return_value=_good(
            option_change="add",
            add_options=[
                {
                    "major": "psychology_bs",
                    "credits_transferable": 50,
                    "reuse_credits_from": "computer_science",  # no known figure for this major
                }
            ],
        ),
    ):
        intent = _classify(known_option_credits={"psychology_ba": 84})
    assert intent.add_options[0].credits_transferable is None


def test_a_literal_number_in_the_message_is_unaffected_by_the_reuse_path():
    """Ordinary extraction ('61 credits apply', stated directly in this
    message) is a different case entirely and must still work exactly as
    before -- only the reuse-from-context path routes through the lookup."""
    with patch(
        "ai.interface._call_model",
        return_value=_good(
            option_change="add",
            add_options=[
                {"major": "computer_science", "credits_transferable": 61, "reuse_credits_from": None}
            ],
        ),
    ):
        intent = _classify(known_option_credits={"psychology_ba": 84})
    assert intent.add_options[0].credits_transferable == 61


def test_prompt_tells_the_model_not_to_write_the_number_itself():
    from ai.interface import INTENT_SYSTEM_PROMPT

    assert "reuse_credits_from" in INTENT_SYSTEM_PROMPT
    assert "do not write" in INTENT_SYSTEM_PROMPT.lower() or "not write the number" in INTENT_SYSTEM_PROMPT.lower()


# --- pending_field_value: ordinary extraction, code decides what happens ---


def test_pending_field_value_is_parsed_from_a_natural_language_reply():
    with patch("ai.interface._call_model", return_value=_good(pending_field_value=86)):
        intent = _classify(
            message="I think 86 apply",
            pending_field_request={"major": "psychology_bs", "field": "credits_transferable"},
        )
    assert intent.pending_field_value == 86


def test_pending_field_value_is_null_when_the_reply_is_unrelated():
    with patch("ai.interface._call_model", return_value=_good(pending_field_value=None)):
        intent = _classify(
            message="What does salary look like instead?",
            pending_field_request={"major": "psychology_bs", "field": "credits_transferable"},
        )
    assert intent.pending_field_value is None
    # And the rest of the intent still classifies normally -- the pending
    # field question doesn't swallow the ability to answer a new one.
    assert intent.topic_scope == "financial"  # _good()'s default topic_scope


def test_prompt_teaches_resolving_a_pending_field_request():
    from ai.interface import INTENT_SYSTEM_PROMPT

    assert "pending_field_value" in INTENT_SYSTEM_PROMPT
    assert "pending_field_request" in INTENT_SYSTEM_PROMPT


# --- prompt content: scoped superlatives, relative priority, restore ------


def test_prompt_distinguishes_scoped_superlatives_from_verdict_requests():
    from ai.interface import INTENT_SYSTEM_PROMPT

    p = INTENT_SYSTEM_PROMPT.lower()
    assert "scoped superlative" in p
    assert "which gets me out fastest" in p
    assert "not a verdict request" in p


def test_prompt_teaches_relative_priority_phrasing():
    from ai.interface import INTENT_SYSTEM_PROMPT

    p = INTENT_SYSTEM_PROMPT.lower()
    assert "i care more about graduating quickly than salary" in p
    assert "relative phrasing" in p


def test_prompt_teaches_named_vs_unnamed_restore():
    from ai.interface import INTENT_SYSTEM_PROMPT

    p = INTENT_SYSTEM_PROMPT.lower()
    assert "restore" in p
    assert "put psychology back" in p or "put them all back" in p


# --- clarification-flag normalization ------------------------------------


def test_clarification_type_without_the_flag_still_needs_clarification():
    """Defensive: a model response with clarification_type set but
    needs_clarification left false must still be treated as needing
    clarification -- the type carries the real signal."""
    with patch(
        "ai.interface._call_model",
        return_value=_good(needs_clarification=False, clarification_type="unclear_topic"),
    ):
        intent = _classify()
    assert intent.needs_clarification


def test_needs_clarification_without_a_type_gets_a_safe_default():
    with patch(
        "ai.interface._call_model",
        return_value=_good(needs_clarification=True, clarification_type=None),
    ):
        intent = _classify()
    assert intent.clarification_type == "unclear_topic"


# --- retry and failure ---------------------------------------------------


def test_invalid_json_triggers_exactly_one_retry_then_succeeds():
    with patch("ai.interface._call_model") as mock_call:
        mock_call.side_effect = ["not json at all", _good()]
        intent = _classify()
    assert mock_call.call_count == 2
    assert intent is not None
    assert intent.topic_scope == "financial"


def test_two_invalid_responses_return_none_not_a_guess():
    with patch("ai.interface._call_model") as mock_call:
        mock_call.side_effect = ["not json", "still not json"]
        intent = _classify()
    assert intent is None


def test_schema_mismatch_is_treated_the_same_as_invalid_json():
    """Valid JSON, but topic_scope isn't one of the allowed literals --
    must be rejected the same way malformed JSON is, not crash."""
    with patch("ai.interface._call_model") as mock_call:
        mock_call.side_effect = [
            json.dumps({"topic_scope": "not_a_real_scope"}),
            json.dumps({"topic_scope": "not_a_real_scope"}),
        ]
        intent = _classify()
    assert intent is None


def test_provider_failure_returns_none_without_raising():
    with patch("ai.interface._call_model", side_effect=RuntimeError("connection reset")):
        intent = _classify()
    assert intent is None


def test_provider_failure_on_retry_also_returns_none():
    with patch("ai.interface._call_model") as mock_call:
        mock_call.side_effect = ["not json", RuntimeError("timeout")]
        intent = _classify()
    assert intent is None


# --- prompt content -------------------------------------------------------


def test_prompt_carries_the_closed_major_list():
    with patch("ai.interface._call_model", return_value=_good()) as mock_call:
        _classify()
    system_arg = mock_call.call_args.args[0]
    assert "computer_science" in system_arg
    assert "Psychology (B.A.)" in system_arg
    assert "Psychology (B.S.)" in system_arg


def test_prompt_distinguishes_priority_statements_from_reactions():
    from ai.interface import INTENT_SYSTEM_PROMPT

    assert "cost matters most" in INTENT_SYSTEM_PROMPT.lower()
    assert "CS looks nice" in INTENT_SYSTEM_PROMPT


def test_prompt_distinguishes_broad_comparison_from_a_verdict_request():
    from ai.interface import INTENT_SYSTEM_PROMPT

    assert "verdict_without_priority" in INTENT_SYSTEM_PROMPT
    assert "compare all four overall" in INTENT_SYSTEM_PROMPT.lower()
