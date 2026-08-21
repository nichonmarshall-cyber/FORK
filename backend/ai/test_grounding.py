"""
Tests for the AI explanation layer's grounding system.

The premise this whole module tests: a language model writing about a
calculation might paraphrase a number's formatting, but every actual
number it states has to trace back to something the engine really
computed. These tests exercise the allowlist/verification/retry/fallback
loop directly, mocking `_call_model` so nothing here makes a real network
call or needs an API key.
"""

import json
from unittest.mock import patch

import pytest

from ai.interface import (
    _all_numbers_grounded,
    _build_number_allowlist,
    _fallback_explanation,
    _grounded_explanation,
    _numeric_variants,
    explain_decision,
)


@pytest.fixture
def sample_result():
    """A realistic formatted_result, small enough to reason about by hand."""
    return {
        "summary": {
            "current_major": "Computer Science",
            "prospective_major": "Psychology (B.S.)",
            "credits_lost": 6,
            "incremental_semesters": 0.8,
            "incremental_tuition": 4800.0,
            "incremental_total_cost": 32930.8,
            "annual_salary_delta": -39839.0,
        },
        "comparison": {
            "staying": {
                "major": "Computer Science",
                "line_items": [
                    {
                        "label": "Credits required — Computer Science",
                        "value": 120,
                        "source": "UNT Registrar Transfer Guide",
                        "source_date": "2025-08-26",
                    }
                ],
            },
            "switching": {
                "major": "Psychology (B.S.)",
                "line_items": [
                    {
                        "label": "Credits required — Psychology (B.S.)",
                        "value": 120,
                        "source": "UNT Registrar Transfer Guide",
                        "source_date": "2025-08-26",
                    }
                ],
            },
        },
        "line_items": [
            {
                "label": "Additional tuition (negative means less)",
                "value": 4800.0,
                "source": "Tuition remaining on prospective path minus current path",
                "source_date": "Calculated",
            },
            {
                "label": "Estimated early-career income delayed",
                "value": 28094.0,
                "source": "Median earnings 1 year after graduation for Computer Science",
                "source_date": "Retrieved 2026-07-31",
            },
        ],
        "earnings_context": [],
        "career_context": [],
        "why_am_i_seeing_this": {
            "assumptions": [
                "Assumes full-time enrollment at 15 credits per semester on both paths."
            ],
            "limitations": [
                "Tuition and earnings data may not be current. Check the date on each line item."
            ],
        },
    }


# --- allowlist construction ----------------------------------------------


def test_allowlist_includes_summary_numbers(sample_result):
    allowlist = _build_number_allowlist(sample_result)
    assert "32931" in allowlist or "32930.8" in allowlist
    assert "0.8" in allowlist
    assert "39839" in allowlist


def test_allowlist_includes_numbers_embedded_in_prose(sample_result):
    """'15 credits per semester' is real data, just inside a string field
    rather than a numeric JSON leaf. It has to be allowed, or the AI
    couldn't even repeat an assumption back without tripping grounding."""
    allowlist = _build_number_allowlist(sample_result)
    assert "15" in allowlist


def test_allowlist_includes_dates(sample_result):
    allowlist = _build_number_allowlist(sample_result)
    assert "2025" in allowlist
    assert "2026" in allowlist


def test_bools_do_not_pollute_allowlist_as_numbers():
    """bool is a subclass of int in Python — True/False must not silently
    become allowlisted "1"/"0", which would make almost any small number
    trivially groundable regardless of the actual data."""
    allowlist = _build_number_allowlist({"warning": True, "other": False})
    # Real evidence a genuine 0 or 1 is allowlisted only when it's actually
    # data — with no other numeric content, nothing should show up here.
    assert allowlist == set()


# --- grounding check -------------------------------------------------------


def test_grounded_text_with_natural_rounding_passes(sample_result):
    allowlist = _build_number_allowlist(sample_result)
    text = (
        "Switching costs about $32,931 more overall and adds 0.8 semesters. "
        "Early-career earnings differ by $39,839/yr."
    )
    assert _all_numbers_grounded(text, allowlist)


def test_invented_number_fails_grounding(sample_result):
    allowlist = _build_number_allowlist(sample_result)
    text = "Switching costs about $50,000 more overall."
    assert not _all_numbers_grounded(text, allowlist)


def test_text_with_no_numbers_is_trivially_grounded(sample_result):
    allowlist = _build_number_allowlist(sample_result)
    text = "Your current major has a stronger reported earnings outlook."
    assert _all_numbers_grounded(text, allowlist)


def test_sign_flip_is_not_treated_as_invention(sample_result):
    """The engine's -39839 delta describes a real number; a model
    describing it as '$39,839 less' (positive magnitude, word for
    direction) is paraphrase, not fabrication."""
    allowlist = _build_number_allowlist(sample_result)
    text = "You'd earn about $39,839 less per year in the reported data."
    assert _all_numbers_grounded(text, allowlist)


# --- shared JSON parsing (markdown-fence tolerance) --------------------
#
# Root cause of a live ai_unavailable failure: the model wrapped its
# response in a ```json ... ``` fence despite the prompt explicitly
# saying not to, and a bare json.loads() choked on the fence characters.
# _parse_model_json() is the one place both classify_intent() and
# _parse_structured_explanation() parse model output, so this fixes both
# call sites at once rather than patching one and leaving the other's
# identical latent bug in place.
#
# Deliberately narrow: normalizes ONE known wrapper shape, nothing else.
# It must never turn into a permissive JSON-repair system.


def test_parse_model_json_accepts_raw_json_unchanged():
    from ai.interface import _parse_model_json

    assert _parse_model_json('{"a": 1}') == {"a": 1}


def test_parse_model_json_strips_a_json_tagged_fence():
    from ai.interface import _parse_model_json

    raw = '```json\n{"a": 1}\n```'
    assert _parse_model_json(raw) == {"a": 1}


def test_parse_model_json_strips_a_plain_fence():
    from ai.interface import _parse_model_json

    raw = '```\n{"a": 1}\n```'
    assert _parse_model_json(raw) == {"a": 1}


def test_parse_model_json_tolerates_surrounding_whitespace():
    from ai.interface import _parse_model_json

    raw = '\n\n  ```json\n{"a": 1}\n```  \n'
    assert _parse_model_json(raw) == {"a": 1}


def test_parse_model_json_handles_a_fenced_array_too():
    from ai.interface import _parse_model_json

    raw = '```json\n[1, 2, 3]\n```'
    assert _parse_model_json(raw) == [1, 2, 3]


def test_parse_model_json_rejects_malformed_json():
    """Not a repair system -- genuinely broken JSON still fails, fence or
    no fence."""
    from ai.interface import _parse_model_json

    assert _parse_model_json('{"a": 1,}') is None
    assert _parse_model_json('```json\n{"a": 1,}\n```') is None
    assert _parse_model_json("not json at all") is None


def test_parse_model_json_rejects_prose_plus_json():
    """The whole-response anchor is the point: a fence-free response with
    the real JSON embedded in prose must NOT be silently extracted --
    that would be scanning/repair behavior, not wrapper normalization."""
    from ai.interface import _parse_model_json

    assert _parse_model_json('Here you go: {"a": 1}') is None
    assert _parse_model_json('{"a": 1}\n\nHope that helps!') is None


def test_parse_model_json_rejects_a_fence_with_trailing_prose_outside_it():
    """The fence must wrap the ENTIRE response -- prose after the closing
    fence means this isn't the known wrapper shape, so it's left alone
    (and correctly fails to parse) rather than having the fence stripped
    out from the middle of the string."""
    from ai.interface import _parse_model_json

    raw = '```json\n{"a": 1}\n```\nLet me know if you need anything else.'
    assert _parse_model_json(raw) is None


def test_intent_classification_survives_a_fenced_live_style_response():
    """End to end against the exact failure mode observed live: a
    well-formed intent wrapped in a ```json fence must now classify
    successfully instead of returning None."""
    from ai.interface import ConversationIntent, classify_intent

    fenced = (
        "```json\n"
        '{"topic_scope": "timeline", "option_change": "none", '
        '"referenced_majors": [], "add_options": [], "remove_options": [], '
        '"priority_update": null, "needs_clarification": false, '
        '"clarification_type": null, "ambiguous_candidates": []}\n'
        "```"
    )
    with patch("ai.interface._call_model", return_value=fenced):
        intent = classify_intent(
            "which gets me out fastest?",
            {"computer_science": "Computer Science"},
            current_topic_scope="broad",
            active_options=["computer_science"],
            stated_priority=None,
            selected_detail_path=None,
        )
    assert isinstance(intent, ConversationIntent)
    assert intent.topic_scope == "timeline"


# --- deterministic fallback -------------------------------------------------


def test_fallback_never_calls_the_model(sample_result):
    """The fallback is pure string formatting — verify it doesn't touch
    _call_model at all, which is what makes it safe to use when the
    provider itself is failing."""
    with patch("ai.interface._call_model") as mock_call:
        _fallback_explanation(sample_result)
        mock_call.assert_not_called()


def test_fallback_states_a_real_cost_direction(sample_result):
    text = _fallback_explanation(sample_result)
    assert "32,931" in text or "$32,931" in text
    assert "more" in text  # cost is positive: switching costs more


def test_fallback_never_reports_missing_earnings_as_a_number():
    result = {
        "summary": {
            "current_major": "Computer Science",
            "prospective_major": "Mechanical & Energy Engineering",
            "incremental_total_cost": 1000.0,
            "incremental_semesters": 0.2,
            "annual_salary_delta": None,
        }
    }
    text = _fallback_explanation(result)
    assert "couldn't be compared" in text
    assert "$0" not in text
    assert "no change" not in text.lower()


def test_fallback_reports_a_genuine_zero_delta_as_no_change_not_missing():
    result = {
        "summary": {
            "current_major": "Computer Science",
            "prospective_major": "Information Technology",
            "incremental_total_cost": 0.0,
            "incremental_semesters": 0.0,
            "annual_salary_delta": 0.0,
        }
    }
    text = _fallback_explanation(result)
    assert "same" in text.lower()
    assert "couldn't be compared" not in text


# --- retry and fallback flow, with the model mocked -------------------------


def test_grounded_first_response_is_used_as_is(sample_result):
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = "Switching costs about $32,931 more overall."
        result = _grounded_explanation("system", "user", sample_result)
    assert result["grounded"] is True
    assert result["used_fallback"] is False
    assert mock_call.call_count == 1


def test_invented_number_triggers_exactly_one_retry(sample_result):
    with patch("ai.interface._call_model") as mock_call:
        mock_call.side_effect = [
            "Switching costs about $50,000 more overall.",  # invented
            "Switching costs about $32,931 more overall.",  # grounded retry
        ]
        result = _grounded_explanation("system", "user", sample_result)
    assert mock_call.call_count == 2
    assert result["used_fallback"] is False
    assert "32,931" in result["text"]


def test_two_ungrounded_responses_fall_back_to_template(sample_result):
    with patch("ai.interface._call_model") as mock_call:
        mock_call.side_effect = [
            "Switching costs about $50,000 more overall.",
            "Switching costs about $99,000 more overall.",
        ]
        result = _grounded_explanation("system", "user", sample_result)
    assert mock_call.call_count == 2
    assert result["used_fallback"] is True
    assert result["grounded"] is True  # the fallback text is always grounded
    assert "50,000" not in result["text"]
    assert "99,000" not in result["text"]


def test_provider_failure_on_first_call_uses_fallback_without_raising(sample_result):
    with patch("ai.interface._call_model", side_effect=RuntimeError("connection reset")):
        result = _grounded_explanation("system", "user", sample_result)
    assert result["used_fallback"] is True
    assert "32,931" in result["text"]  # the deterministic template still ran


def test_provider_failure_on_retry_uses_fallback_without_raising(sample_result):
    with patch("ai.interface._call_model") as mock_call:
        mock_call.side_effect = [
            "Switching costs about $50,000 more overall.",  # invented, triggers retry
            RuntimeError("timeout"),  # retry itself fails
        ]
        result = _grounded_explanation("system", "user", sample_result)
    assert result["used_fallback"] is True


# --- explain_decision (the public function main.py calls) -------------------

_AVAILABLE_NODES = [
    {"id": "financial", "label": "Financial Impact"},
    {"id": "salary_outlook", "label": "Salary Outlook"},
]


def test_explain_decision_includes_node_context_in_the_prompt(sample_result):
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = json.dumps(
            {
                "direct_answer": "This node covers additional tuition.",
                "key_points": [],
                "limitations": [],
                "still_useful_for": [],
                "next_step": None,
                "related_node_ids": [],
            }
        )
        explain_decision(
            sample_result,
            question="Why does this cost more?",
            node_id="financial",
            node_label="Financial Impact",
            node_question="What does switching cost?",
            available_nodes=_AVAILABLE_NODES,
        )
    system_arg = mock_call.call_args[0][0]
    assert "Financial Impact" in system_arg
    # The valid-id list has to actually reach the prompt, or the model has
    # no way to know which ids are real.
    assert "financial" in system_arg
    assert "salary_outlook" in system_arg


def test_explain_decision_returns_structured_explanation(sample_result):
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = json.dumps(
            {
                "direct_answer": "Switching costs about $32,931 more.",
                "key_points": [{"title": "Cost", "explanation": "Additional tuition of $4,800."}],
                "limitations": [],
                "still_useful_for": ["Comparing tuition"],
                "next_step": None,
                "related_node_ids": [],
            }
        )
        result = explain_decision(
            sample_result,
            question="q",
            node_id=None,
            node_label=None,
            node_question=None,
            available_nodes=_AVAILABLE_NODES,
        )
    assert set(result.keys()) == {"explanation", "used_fallback", "topic_scope"}
    assert result["used_fallback"] is False
    assert result["explanation"].direct_answer == "Switching costs about $32,931 more."
    assert result["explanation"].key_points[0].title == "Cost"


def test_explain_decision_drops_a_related_node_id_the_model_invented(sample_result):
    """The model naming a plausible-but-fake node id must not reach the
    caller — only ids present in available_nodes are allowed through."""
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = json.dumps(
            {
                "direct_answer": "Answer.",
                "key_points": [],
                "limitations": [],
                "still_useful_for": [],
                "next_step": None,
                "related_node_ids": ["salary_outlook", "not_a_real_node"],
            }
        )
        result = explain_decision(
            sample_result,
            question="q",
            node_id=None,
            node_label=None,
            node_question=None,
            available_nodes=_AVAILABLE_NODES,
        )
    assert result["explanation"].related_node_ids == ["salary_outlook"]


def test_explain_decision_falls_back_on_invalid_json(sample_result):
    with patch("ai.interface._call_model", return_value="This is prose, not JSON."):
        result = explain_decision(
            sample_result, question="q", node_id=None, node_label=None, node_question=None
        )
    assert result["used_fallback"] is True
    assert result["explanation"].direct_answer  # fallback still produces real content


def test_explain_decision_survives_a_fenced_response_instead_of_falling_back(sample_result):
    """The same shared parser fix as classify_intent() -- a well-formed
    explanation wrapped in a ```json fence must be used as-is, not
    treated as unparseable and downgraded to the deterministic template."""
    fenced = (
        "```json\n"
        + json.dumps(
            {
                "direct_answer": "Switching costs about $32,931 more.",
                "key_points": [],
                "limitations": [],
                "still_useful_for": [],
                "next_step": None,
                "related_node_ids": [],
            }
        )
        + "\n```"
    )
    with patch("ai.interface._call_model", return_value=fenced):
        result = explain_decision(
            sample_result, question="q", node_id=None, node_label=None, node_question=None
        )
    assert result["used_fallback"] is False
    assert result["explanation"].direct_answer == "Switching costs about $32,931 more."


def test_explain_decision_falls_back_on_schema_mismatch(sample_result):
    """Valid JSON, but missing the required direct_answer field — must be
    treated the same as invalid JSON, not crash."""
    with patch("ai.interface._call_model", return_value=json.dumps({"key_points": []})):
        result = explain_decision(
            sample_result, question="q", node_id=None, node_label=None, node_question=None
        )
    assert result["used_fallback"] is True


def test_explain_decision_falls_back_on_invented_number_in_structured_response(sample_result):
    with patch(
        "ai.interface._call_model",
        return_value=json.dumps(
            {
                "direct_answer": "Switching costs about $999,999 more.",
                "key_points": [],
                "limitations": [],
                "still_useful_for": [],
                "next_step": None,
                "related_node_ids": [],
            }
        ),
    ):
        result = explain_decision(
            sample_result, question="q", node_id=None, node_label=None, node_question=None
        )
    assert result["used_fallback"] is True
    assert "999,999" not in result["explanation"].direct_answer


# --- topic focus instructions ------------------------------------------------


def test_each_topic_scope_gets_a_distinct_focused_instruction():
    """Every classified topic_scope must produce a genuinely different
    instruction -- otherwise Compare One's questions would tend toward
    the same generic answer regardless of what was actually classified.
    This replaced keyword-matching the question text directly (see
    ai.interface.classify_intent); the scope now comes from the shared
    intent classifier instead."""
    from ai.interface import _topic_focus_instruction

    scopes = ["broad", "financial", "timeline", "credits", "career"]
    focuses = {_topic_focus_instruction(s) for s in scopes}
    assert len(focuses) == 5


def test_unrecognized_scope_gets_the_broad_focus_instruction():
    from ai.interface import _topic_focus_instruction

    assert _topic_focus_instruction("not_a_real_scope") == _topic_focus_instruction("broad")


# --- derived-relationship guard ----------------------------------------
#
# The failure mode these tests exist for: two individually real figures,
# each grounded on its own, can still have an INVENTED relationship
# stated between them ("$39,839 is roughly five times larger than
# $8,498" -- both dollar amounts are real, "five times larger" is
# arithmetic Fork's engine never performed). Numeric grounding alone
# can't catch this since every literal number in the sentence traces
# back to real data; a second, independent check is required.


def test_grounded_individual_values_still_rejected_when_a_ratio_is_invented(sample_result):
    """The core case: every dollar figure in the sentence is real and
    grounded on its own, but the '5 times larger' relationship between
    them was never computed by the backend. Must still be rejected."""
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = json.dumps(
            {
                "direct_answer": (
                    "The $39,839 earnings gap is roughly five times larger "
                    "than the $8,498 switching cost."
                ),
                "key_points": [],
                "limitations": [],
                "still_useful_for": [],
                "next_step": None,
                "related_node_ids": [],
            }
        )
        result = explain_decision(
            sample_result, question="q", node_id=None, node_label=None, node_question=None
        )
    assert result["used_fallback"] is True
    assert "five times" not in result["explanation"].direct_answer.lower()


@pytest.mark.parametrize(
    "phrasing",
    [
        "the switching cost could theoretically be recovered in well under a year",
        "you would pay off the switching cost within a year",
        "within a year, the extra earnings would pay for the switch",
        "in under two years you would earn back the difference",
        "the ROI on switching looks strong",
        "switching seems worth it financially",
        "you would break even on the cost within 12 months",
        "this is your break-even point",
        "the gap is 5x larger than the switching cost",
        "psychology earnings are 43% lower than computer science",
        "switching would pay for itself quickly",
        "you'd recoup the expense in about a year",
    ],
)
def test_wording_variants_of_payback_roi_ratio_claims_are_rejected(sample_result, phrasing):
    """Not just the exact screenshot phrasing -- reworded variants of the
    same underlying claim (payback period, ROI, ratio, percent
    comparison) must all be caught, since a model asked not to say
    something one way will often say it another way instead."""
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = json.dumps(
            {
                "direct_answer": f"Switching costs more, and {phrasing}.",
                "key_points": [],
                "limitations": [],
                "still_useful_for": [],
                "next_step": None,
                "related_node_ids": [],
            }
        )
        result = explain_decision(
            sample_result, question="q", node_id=None, node_label=None, node_question=None
        )
    assert result["used_fallback"] is True, f"should have rejected: {phrasing!r}"


def test_legitimate_backend_relationships_are_still_allowed(sample_result):
    """The guard must not be so broad it rejects an answer that simply
    RESTATES a relationship the backend itself already computed --
    annual_salary_delta is a real field the engine produces, and
    describing it in plain language must still pass."""
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = json.dumps(
            {
                "direct_answer": (
                    "Reported early-career earnings differ by $39,839 per year "
                    "between the two majors, based on the available data."
                ),
                "key_points": [
                    {
                        "title": "Additional cost",
                        "explanation": "Switching costs an estimated $4,800 more in tuition.",
                    }
                ],
                "limitations": [],
                "still_useful_for": [],
                "next_step": None,
                "related_node_ids": [],
            }
        )
        result = explain_decision(
            sample_result, question="q", node_id=None, node_label=None, node_question=None
        )
    assert result["used_fallback"] is False


def test_legitimate_percent_growth_figure_from_source_data_is_not_flagged():
    """A real percentage that already exists in the source data (e.g. a
    BLS growth projection) must not be rejected just because it's a
    percent sign near a number -- only NEW percent COMPARISONS the model
    invents should be caught."""
    from ai.interface import _has_invented_relationship, _build_number_allowlist

    result = {
        "summary": {"current_major": "A", "prospective_major": "B"},
        "career_context": [
            {
                "major": "A",
                "occupations": [{"title": "X", "percent_change_2024_2034": 9.1}],
            }
        ],
    }
    allowlist = _build_number_allowlist(result)
    text = "BLS projects 9.1% growth for this occupation over the next decade."
    assert _has_invented_relationship(text, allowlist) is False


def test_relationship_violation_triggers_a_targeted_retry_not_the_generic_one(sample_result):
    """The retry after a relationship violation should use the
    relationship-specific corrective instruction, not the generic
    grounding one -- confirms the two failure modes are tracked
    separately rather than collapsed into one message."""
    from ai.interface import RELATIONSHIP_RETRY_SUFFIX

    with patch("ai.interface._call_model") as mock_call:
        mock_call.side_effect = [
            json.dumps(
                {
                    "direct_answer": "The gap is five times larger than the cost.",
                    "key_points": [],
                    "limitations": [],
                    "still_useful_for": [],
                    "next_step": None,
                    "related_node_ids": [],
                }
            ),
            json.dumps(
                {
                    "direct_answer": "Switching costs more overall.",
                    "key_points": [],
                    "limitations": [],
                    "still_useful_for": [],
                    "next_step": None,
                    "related_node_ids": [],
                }
            ),
        ]
        explain_decision(
            sample_result, question="q", node_id=None, node_label=None, node_question=None
        )
    second_call_system_prompt = mock_call.call_args_list[1][0][0]
    assert RELATIONSHIP_RETRY_SUFFIX.strip() in second_call_system_prompt


def test_next_step_schema_is_unchanged_action_and_reason():
    """Explicit regression guard: next_step keeps {action, reason}, not a
    renamed {title, reason} -- per the decision not to make an
    unnecessary breaking schema change."""
    from ai.interface import NextStep

    fields = NextStep.model_fields
    assert set(fields.keys()) == {"action", "reason"}


def test_explain_decision_has_no_way_to_receive_prior_ai_prose_as_context():
    """Structural guarantee for requirement 7: previous Fork answers must
    never become authoritative evidence for a later question. The
    strongest version of that guarantee isn't a behavioral test (which
    only proves today's code path is safe) -- it's that the function
    signature has no parameter a caller COULD use to pass prior AI text
    in, so there's nothing to accidentally wire up later. Only
    `formatted_result` (this request's own fresh server-side
    recalculation) supplies factual content; `question` is free text the
    student typed, never model output from a previous turn."""
    import inspect

    from ai.interface import explain_decision

    params = set(inspect.signature(explain_decision).parameters.keys())
    assert params == {
        "formatted_result",
        "question",
        "node_id",
        "node_label",
        "node_question",
        "available_nodes",
        "topic_scope",
    }
    # None of these params could plausibly carry prior AI-generated prose.
    for suspicious in ("history", "previous", "prior", "context", "conversation"):
        assert not any(suspicious in p for p in params), (
            f"a parameter matching {suspicious!r} exists -- verify it can't "
            "carry untrusted prior AI text as if it were fact"
        )

    # --- subjective magnitude verdicts and unsupported extrapolation -------
#
# All of these were observed in real output before this pass. The engine
# ranks nothing and reports a single one-year earnings snapshot, so any
# claim that one figure overwhelms another, or that a gap repeats
# annually, is the model's own judgment presented as a finding.


@pytest.mark.parametrize(
    "phrasing",
    [
        "the single most consequential difference is the earnings gap",
        "that figure dwarfs the estimated additional cost",
        "the earnings gap dominates everything else",
        "it is the largest number in this comparison by a wide margin",
        "this carries the most weight in the overall difference",
        "the cost difference is overwhelmed by the earnings gap",
        "the earnings gap is an annual figure that recurs",
        "that difference repeats every year",
    ],
)
def test_subjective_magnitude_and_recurrence_claims_are_rejected(sample_result, phrasing):
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = json.dumps(
            {
                "direct_answer": f"Fork's comparison shows that {phrasing}.",
                "key_points": [],
                "limitations": [],
                "still_useful_for": [],
                "next_step": None,
                "related_node_ids": [],
            }
        )
        result = explain_decision(
            sample_result, question="q", node_id=None, node_label=None, node_question=None
        )
    assert result["used_fallback"] is True, f"should have rejected: {phrasing!r}"


# --- unit reframing --------------------------------------------------------
#
# The engine only ever states semester counts, never a year-equivalent --
# "almost a full academic year" is a unit conversion Fork's engine never
# performed, the same category of invention as an unsupported ratio, just
# in a different unit instead of a multiplier.


@pytest.mark.parametrize(
    "phrasing",
    [
        "that's almost a full year of delay",
        "nearly a year longer",
        "about a year of extra time",
        "close to an academic year",
    ],
)
def test_unit_reframing_into_years_is_rejected(sample_result, phrasing):
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = json.dumps(
            {
                "direct_answer": f"Switching takes longer -- {phrasing}.",
                "key_points": [],
                "limitations": [],
                "still_useful_for": [],
                "next_step": None,
                "related_node_ids": [],
            }
        )
        result = explain_decision(
            sample_result, question="q", node_id=None, node_label=None, node_question=None
        )
    assert result["used_fallback"] is True, f"should have rejected: {phrasing!r}"


def test_a_literal_year_mention_unrelated_to_duration_is_not_falsely_rejected():
    """The guard targets a DURATION reframed into years, not any mention
    of the word "year" -- a dataset release year or similar must not trip
    it."""
    from ai.interface import _build_number_allowlist, _has_invented_relationship

    allowlist = _build_number_allowlist({"source": "College Scorecard, released 2026"})
    text = "This figure was retrieved from data released in 2026."
    assert _has_invented_relationship(text, allowlist) is False


@pytest.mark.parametrize(
    "phrasing",
    [
        "The largest difference in Fork's current comparison is early-career earnings.",
        "Fork currently estimates that 6 credits may not apply toward the prospective degree.",
        "The available College Scorecard data reports figures for the broader graduate group.",
        "Based on the information you entered, most of your credits are currently counted.",
        "No single factor clearly separates the two options in the current comparison.",
        "An official what-if degree audit could confirm which credits apply.",
        "The available data does not show a difference here.",
    ],
)
def test_approved_fork_voice_is_not_rejected(sample_result, phrasing):
    """The guard has to leave Fork's own approved phrasings alone. If any
    of these trip it, the patterns are too broad and Fork would fall back
    to the deterministic template constantly."""
    from ai.interface import _build_number_allowlist, _has_invented_relationship

    allowlist = _build_number_allowlist(sample_result)
    assert _has_invented_relationship(phrasing, allowlist) is False


# --- cross-domain importance ranking -------------------------------------
#
# Observed in a real conversational test: "This matters more than the
# other dimensions here... making it the single dimension with the most
# downstream consequences." Fork's engine never weighs cost against
# timeline against career -- any claim that one dimension outranks
# another is the model's own judgment, not a finding, even when every
# number in the sentence is individually real and grounded.


@pytest.mark.parametrize(
    "phrasing",
    [
        "the earnings difference matters more than the other dimensions here",
        "this makes it the single dimension with the most downstream consequences",
        "the timeline impact takes priority over the financial one",
        "the cost difference outweighs the credit-transfer concerns",
        "this is the most important factor in the comparison",
        "career outlook is the most significant consideration here",
    ],
)
def test_cross_domain_importance_claims_are_rejected(sample_result, phrasing):
    """Every one of these is a ranking claim ACROSS unlike dimensions
    (cost vs. timeline vs. career), which the engine never computes --
    distinct from restating a real number or calling out the largest
    figure WITHIN one already-grounded comparison, which stays approved
    Fork voice (see test_approved_fork_voice_is_not_rejected)."""
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = json.dumps(
            {
                "direct_answer": f"Switching costs more, and {phrasing}.",
                "key_points": [],
                "limitations": [],
                "still_useful_for": [],
                "next_step": None,
                "related_node_ids": [],
            }
        )
        result = explain_decision(
            sample_result, question="q", node_id=None, node_label=None, node_question=None
        )
    assert result["used_fallback"] is True, f"should have rejected: {phrasing!r}"


def test_prompt_already_forbids_cross_domain_ranking_for_multi_option():
    """The multi-option prompt already tells the model not to do this --
    the regex guard above is the check that doesn't depend on it
    listening, same philosophy as the payback/ROI guard."""
    from ai.interface import MULTI_COMPARISON_SYSTEM_PROMPT as p

    assert "never say one matters more than another" in p.lower()


# --- alternative-count wording ---------------------------------------------
#
# Observed in a real conversational test: a CAREER answer covering four
# active options opened with "the biggest difference across all three
# alternatives" -- a spelled-out count that never matches the digit-based
# numeric-grounding regex, so a plain miscount slipped through ungrounded.


def test_counts_alternatives_correctly_accepts_a_matching_spelled_count():
    from ai.interface import _counts_alternatives_correctly

    assert _counts_alternatives_correctly(
        "the biggest difference across all four alternatives", active_option_count=4
    )


def test_counts_alternatives_correctly_rejects_a_mismatched_spelled_count():
    from ai.interface import _counts_alternatives_correctly

    assert not _counts_alternatives_correctly(
        "the biggest difference across all three alternatives", active_option_count=4
    )


def test_counts_alternatives_correctly_skips_the_check_when_not_applicable():
    """Compare One never passes an active_option_count -- always passes
    regardless of what the text says, since the check doesn't apply."""
    from ai.interface import _counts_alternatives_correctly

    assert _counts_alternatives_correctly(
        "across all three alternatives", active_option_count=None
    )


def test_multi_comparison_rejects_a_miscounted_alternative_total():
    """End to end: explain_multi_comparison() must fall back to the
    deterministic template when the model states a spelled-out
    alternative count that doesn't match the view's actual option list --
    reproducing the exact regression (four active options, model said
    'three')."""
    from ai.interface import explain_multi_comparison

    view = {
        "topic_scope": "career",
        "current_major": "Mechanical & Energy Engineering",
        "credits_completed": 90,
        "options": [
            {"major": "Information Technology", "status": "calculated", "data": {}},
            {"major": "Business Administration", "status": "calculated", "data": {}},
            {"major": "Computer Science", "status": "calculated", "data": {}},
            {"major": "Psychology (B.S.)", "status": "calculated", "data": {}},
        ],
        "assumptions": [],
        "limitations": [],
    }
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = json.dumps(
            {
                "direct_answer": (
                    "The biggest difference across all three alternatives is career outlook."
                ),
                "key_points": [],
                "limitations": [],
                "still_useful_for": [],
                "next_step": None,
                "related_node_ids": [],
            }
        )
        result = explain_multi_comparison(view, "which one has the best career outlook?")
    assert result["used_fallback"] is True


def test_prompt_instructs_against_repeating_the_same_finding():
    """Sections must each add something new. Prompt-level rule --
    asserted structurally since there's no deterministic way to test
    'did the model repeat itself' without a live call."""
    from ai.interface import DECISION_QUESTION_SYSTEM_PROMPT as p

    assert "what new information does this add" in p.lower()
    assert "do not restate the same finding" in p.lower()


def test_prompt_carries_the_certainty_vocabulary():
    from ai.interface import DECISION_QUESTION_SYSTEM_PROMPT as p

    for term in ("KNOWN", "CALCULATED", "ESTIMATED", "UNRESOLVED"):
        assert term in p


def test_prompt_forbids_treating_typed_credit_counts_as_an_audit():
    from ai.interface import DECISION_QUESTION_SYSTEM_PROMPT as p

    assert "not an official audit" in p.lower()
    assert "count toward nothing" in p  # named explicitly as forbidden
    assert "electives" in p.lower()


def test_prompt_requires_naming_the_broader_category_for_earnings():
    from ai.interface import DECISION_QUESTION_SYSTEM_PROMPT as p

    assert "broader" in p.lower()
    assert "never claim the difference recurs" in p.lower()


def test_prompt_limits_related_nodes_to_a_handful():
    from ai.interface import DECISION_QUESTION_SYSTEM_PROMPT as p

    assert "1-3" in p