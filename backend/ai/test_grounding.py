"""
Tests for the AI explanation layer's grounding system.

The premise this whole module tests: a language model writing about a
calculation might paraphrase a number's formatting, but every actual
number it states has to trace back to something the engine really
computed. These tests exercise the allowlist/verification/retry/fallback
loop directly, mocking `_call_model` so nothing here makes a real network
call or needs an API key.
"""

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


def test_explain_decision_includes_node_context_in_the_prompt(sample_result):
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = "This node covers additional tuition."
        explain_decision(
            sample_result,
            question="Why does this cost more?",
            node_id="financial",
            node_label="Financial Impact",
            node_question="What does switching cost?",
        )
    system_arg = mock_call.call_args[0][0]
    assert "Financial Impact" in system_arg


def test_explain_decision_returns_grounded_and_fallback_flags(sample_result):
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = "Switching costs about $32,931 more."
        result = explain_decision(
            sample_result, question="q", node_id=None, node_label=None, node_question=None
        )
    assert set(result.keys()) == {"answer", "grounded", "used_fallback"}
    assert result["grounded"] is True