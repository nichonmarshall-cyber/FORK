"""
Invalid input must be rejected before anything reaches a model provider.

`/explain` recomputes the calculation rather than trusting a client-supplied
result, so it accepts the same inputs `/calculate` does and has to reject the
same ones. The subtlety is *when*.

Before this was fixed, `ExplainRequest` declared bare `int` fields with no
bounds. FastAPI accepted `credits_completed: -5`, the route called
`handle_pairwise_turn` — which classifies intent, a provider call — and only
afterwards built `ChangeMajorRequest`, where the constraint actually lived.
Two things followed:

  * Fork paid for a round trip on a request that was always going to 422.
  * If that call failed, the student was told "Ask Fork is temporarily
    unavailable" when the real problem was their own input.

The bug was invisible whenever ANTHROPIC_API_KEY was set, because
classification would succeed and the 422 would surface a few lines later.
That is why these tests patch the provider to explode rather than checking a
status code: a test that only asserts 422 passes for the wrong reason on a
machine with a key. Here, if validation order regresses, the boom is
unmissable.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

_VALID_BODY = {
    "current_major": "computer_science",
    "prospective_major": "information_technology",
    "credits_completed": 72,
    "credits_transferable": 66,
    "question": "How much longer will this take?",
}


class ProviderWasCalled(AssertionError):
    """Raised by the mock. Reaching it at all is the failure."""


def _explode(*args, **kwargs):
    raise ProviderWasCalled(
        "A model provider was called before the request was validated."
    )


@pytest.mark.parametrize(
    "label, override",
    [
        ("negative completed credits", {"credits_completed": -5}),
        ("completed credits above the cap", {"credits_completed": 999}),
        ("negative transferable credits", {"credits_transferable": -1}),
        (
            "transferable exceeding completed",
            {"credits_completed": 60, "credits_transferable": 90},
        ),
        ("in-progress hours above the cap", {"credits_in_progress": 99}),
        ("required credits below the floor", {"prospective_credits_required": 0}),
    ],
)
def test_invalid_input_is_rejected_without_touching_a_provider(label, override):
    """Every constraint ChangeMajorInputs enforces, enforced at the boundary.

    The patches cover both the classifier and the explanation generator, so
    the test fails whichever one a future refactor happens to reach first.
    """
    # Patched on ai.interface rather than the orchestrator: the orchestrator
    # imports classify_intent lazily inside the function, so the module
    # attribute is the only binding that exists to intercept.
    with (
        patch("ai.interface.classify_intent", side_effect=_explode),
        patch("ai.interface.explain_decision", side_effect=_explode),
    ):
        response = client.post(
            "/decision-paths/change-major/explain",
            json={**_VALID_BODY, **override},
        )

    assert response.status_code == 422, label
    detail = response.json()["detail"]
    assert detail["status"] == "validation_error", label
    # Fork's shape, not FastAPI's raw error list -- the frontend's
    # parseApiError understands one format and shouldn't have to learn two
    # depending on which layer caught the problem.
    assert isinstance(detail["errors"], list) and detail["errors"], label
    assert detail["message"], label


def test_the_mock_would_actually_fire_on_a_valid_request():
    """Proof the test above isn't passing vacuously.

    If the patch targets were wrong, every case would 'pass' while silently
    exercising nothing. A valid request has to reach the classifier, so this
    one must raise.
    """
    with patch("ai.interface.classify_intent", side_effect=_explode):
        with pytest.raises(ProviderWasCalled):
            client.post("/decision-paths/change-major/explain", json=_VALID_BODY)


def test_explain_and_calculate_agree_on_what_is_invalid():
    """The two endpoints share a constraint set, so they must reject the
    same input. Divergence would mean a figure Ask Fork will discuss but
    the engine won't compute."""
    bad = {**_VALID_BODY, "credits_completed": -5}

    with patch("ai.interface.classify_intent", side_effect=_explode):
        explained = client.post("/decision-paths/change-major/explain", json=bad)

    calculated = client.post(
        "/decision-paths/change-major/calculate",
        json={k: v for k, v in bad.items() if k != "question"},
    )

    assert explained.status_code == calculated.status_code == 422
    assert (
        explained.json()["detail"]["status"]
        == calculated.json()["detail"]["status"]
        == "validation_error"
    )