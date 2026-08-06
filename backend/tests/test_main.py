"""
Tests for the API layer's institution_id and major-key handling.

This is the first test file for main.py itself — everything else so far
tested the engine and the loader in isolation. These tests exercise the
FastAPI app the way an HTTP client actually would: unknown institutions
come back as a clean 404 instead of a stack trace, omitting institution_id
entirely still works because it defaults to "unt", and the three
major-resolution special cases (legacy alias, ambiguous, unsupported) come
back as structured, actionable responses rather than a generic 422 or an
engine ValueError.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

_VALID_BODY = {
    "current_major": "computer_science",
    "prospective_major": "information_technology",
    "credits_completed": 72,
    "credits_transferable": 60,
}


def test_calculate_defaults_to_unt_when_institution_id_omitted():
    """Every caller that existed before Stage 2 didn't send institution_id
    at all. That has to keep working exactly as before."""
    res = client.post("/decision-paths/change-major/calculate", json=_VALID_BODY)
    assert res.status_code == 200
    # Real 2025-2026 UNT data (CS 120 hours, IT 121 hours) through the
    # verified semester-based tuition model — see
    # data_loading/tests/test_loader.py for how this number is derived.
    assert res.json()["summary"]["incremental_tuition"] == 5239.87


def test_calculate_accepts_explicit_institution_id():
    body = {**_VALID_BODY, "institution_id": "unt"}
    res = client.post("/decision-paths/change-major/calculate", json=body)
    assert res.status_code == 200


def test_calculate_rejects_unknown_institution_with_404_not_500():
    """An unknown institution_id must never reach the engine or produce a
    stack trace — it's a client error (bad institution), not a server one."""
    body = {**_VALID_BODY, "institution_id": "hogwarts"}
    res = client.post("/decision-paths/change-major/calculate", json=body)
    assert res.status_code == 404
    assert "hogwarts" in res.json()["detail"]
    assert "unt" in res.json()["detail"]  # known IDs listed, so the client can recover


def test_health_check_still_works():
    """Cheap smoke test that Stage 2's changes didn't break app startup."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_legacy_mechanical_engineering_key_still_works_with_a_warning():
    """Old callers using the retired 'mechanical_engineering' key must not
    be broken by the rename — the request should still succeed, with a
    warning telling the caller the key changed."""
    body = {
        "current_major": "computer_science",
        "prospective_major": "mechanical_engineering",
        "credits_completed": 60,
        "credits_transferable": 30,
    }
    res = client.post("/decision-paths/change-major/calculate", json=body)
    assert res.status_code == 200
    data = res.json()
    assert data["comparison"]["switching"]["major"] == "Mechanical & Energy Engineering"
    assert any("renamed" in w for w in data.get("warnings", []))


def test_generic_psychology_returns_clarification_not_a_500():
    body = {
        "current_major": "computer_science",
        "prospective_major": "psychology",
        "credits_completed": 60,
        "credits_transferable": 30,
    }
    res = client.post("/decision-paths/change-major/calculate", json=body)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["status"] == "clarification_required"
    assert detail["field"] == "prospective_major"
    assert set(detail["options"]) == {"psychology_ba", "psychology_bs"}


def test_nursing_returns_documented_unsupported_response():
    body = {
        "current_major": "computer_science",
        "prospective_major": "nursing",
        "credits_completed": 60,
        "credits_transferable": 30,
    }
    res = client.post("/decision-paths/change-major/calculate", json=body)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["status"] == "unsupported_program"
    assert detail["field"] == "prospective_major"
    assert "UNT Health" in detail["message"]


def test_transferable_exceeding_completed_returns_clean_structured_error():
    """The actual bug this test suite exists to catch: Pydantic's raw
    ValidationError repr includes a docs URL and internal type/input_value
    fields that used to leak straight to the client. This locks in the
    replacement shape so a future refactor can't reintroduce str(e)."""
    body = {**_VALID_BODY, "credits_completed": 72, "credits_transferable": 74}
    res = client.post("/decision-paths/change-major/calculate", json=body)
    assert res.status_code == 422
    detail = res.json()["detail"]

    assert detail["status"] == "validation_error"
    assert "credits_transferable cannot exceed credits_completed" in detail["message"]
    assert detail["errors"][0]["field"] == "credits_transferable"

    # The specific internals that used to leak. If any of these ever show
    # up again, str(e) crept back in somewhere.
    raw = res.text
    assert "errors.pydantic.dev" not in raw
    assert "type=value_error" not in raw
    assert "input_value=" not in raw
    assert "For further information visit" not in raw


def test_negative_credits_returns_clean_structured_error():
    body = {**_VALID_BODY, "credits_completed": -5}
    res = client.post("/decision-paths/change-major/calculate", json=body)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["status"] == "validation_error"
    assert "errors.pydantic.dev" not in res.text
    body = {
        "current_major": "psychology_ba",
        "prospective_major": "computer_science",
        "credits_completed": 60,
        "credits_transferable": 30,
    }
    res = client.post("/decision-paths/change-major/calculate", json=body)
    assert res.status_code == 200
    assert "warnings" not in res.json()


# --- /decision-paths/change-major/explain ------------------------------

_EXPLAIN_BODY = {**_VALID_BODY, "question": "Explain the biggest difference"}


def test_explain_returns_a_grounded_answer():
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = "Switching costs more overall based on the tuition and timeline figures."
        res = client.post("/decision-paths/change-major/explain", json=_EXPLAIN_BODY)
    assert res.status_code == 200
    data = res.json()
    assert set(data.keys()) == {"answer", "used_fallback", "selected_node_id"}
    assert data["used_fallback"] is False
    assert len(data["answer"]) > 0


def test_explain_passes_selected_node_context_to_the_model():
    body = {
        **_EXPLAIN_BODY,
        "selected_node_id": "financial",
        "selected_node_label": "Financial Impact",
        "selected_node_question": "What does switching cost?",
    }
    with patch("ai.interface._call_model") as mock_call:
        mock_call.return_value = "The additional cost comes from tuition and delayed income."
        res = client.post("/decision-paths/change-major/explain", json=body)
    assert res.status_code == 200
    assert res.json()["selected_node_id"] == "financial"
    system_arg = mock_call.call_args[0][0]
    assert "Financial Impact" in system_arg


def test_explain_falls_back_gracefully_when_the_provider_fails():
    """A provider exception must never reach the client as a raw error —
    explain_decision's internal fallback should produce a normal 200
    response instead."""
    with patch("ai.interface._call_model", side_effect=RuntimeError("connection reset")):
        res = client.post("/decision-paths/change-major/explain", json=_EXPLAIN_BODY)
    assert res.status_code == 200
    data = res.json()
    assert data["used_fallback"] is True
    assert "RuntimeError" not in data["answer"]
    assert "connection reset" not in data["answer"]
    assert "Traceback" not in res.text


def test_explain_rejects_invalid_inputs_the_same_way_calculate_does():
    """The explain endpoint recomputes the calculation from inputs rather
    than trusting a client-supplied result, so bad inputs must fail with
    the same clean validation error /calculate would give — not a
    different, AI-specific error shape."""
    body = {**_EXPLAIN_BODY, "credits_completed": -5}
    res = client.post("/decision-paths/change-major/explain", json=body)
    assert res.status_code == 422
    assert res.json()["detail"]["status"] == "validation_error"


def test_explain_never_leaks_raw_errors_regardless_of_failure_mode():
    with patch("ai.interface._call_model", side_effect=Exception("some internal detail")):
        res = client.post("/decision-paths/change-major/explain", json=_EXPLAIN_BODY)
    assert "some internal detail" not in res.text
    assert "Exception" not in res.text