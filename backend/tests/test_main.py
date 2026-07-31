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


def test_specific_psychology_variant_works_without_clarification():
    body = {
        "current_major": "psychology_ba",
        "prospective_major": "computer_science",
        "credits_completed": 60,
        "credits_transferable": 30,
    }
    res = client.post("/decision-paths/change-major/calculate", json=body)
    assert res.status_code == 200
    assert "warnings" not in res.json()
