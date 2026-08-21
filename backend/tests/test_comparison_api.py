"""
API tests for the multi-option comparison endpoints.

Runs against the real institution data files, so these also catch a
mismatch between what the engine expects and what the data actually
contains. The AI explanation is patched out -- these test the plumbing,
the state handling, and the HTTP contract, none of which should need a
model to verify.
"""

import pytest
from fastapi.testclient import TestClient

import main
from conversation.session import SESSIONS

client = TestClient(main.app)

START = "/decision-paths/change-major/comparison/start"
ASK = "/decision-paths/change-major/comparison/ask"


@pytest.fixture(autouse=True)
def stub_the_model(monkeypatch):
    """No API key needed. Natural-language understanding and the
    explanation layer are each exercised in their own tests (ai/test_intent.py,
    ai/test_grounding.py, conversation/test_orchestrator.py) -- here a
    small deterministic fake stands in for the real classifier and
    explainer so these HTTP-level tests can assert on the plumbing and
    state handling without a live model call."""

    def fake_explain(view, question, available_nodes=None):
        from ai.interface import DecisionExplanation

        return {
            "explanation": DecisionExplanation(
                direct_answer=f"Stub answer at scope {view['topic_scope']}."
            ),
            "used_fallback": False,
        }

    def fake_classify(
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
        from ai.interface import ConversationIntent, OptionMajorInput

        text = message.lower()
        if "cost" in text:
            return ConversationIntent(topic_scope="financial")
        if "career" in text:
            return ConversationIntent(topic_scope="career")
        if "just compare cs and it" in text:
            return ConversationIntent(
                topic_scope="unchanged",
                option_change="replace",
                add_options=[
                    OptionMajorInput(major="computer_science"),
                    OptionMajorInput(major="information_technology"),
                ],
            )
        if "leaning toward" in text:
            # A preference, not an instruction -- no topic word either, so
            # a real classifier with nothing to inherit from would default
            # broad rather than offer "unchanged" with nothing behind it.
            return ConversationIntent(topic_scope="broad")
        if "better" in text or "best" in text:
            return ConversationIntent(
                topic_scope="unclear",
                needs_clarification=True,
                clarification_type="verdict_without_priority",
            )
        return ConversationIntent(topic_scope="broad")

    import conversation.orchestrator as orch

    original = orch.handle_turn

    def patched(
        session,
        message,
        reference_data,
        selected_detail_path=None,
        available_nodes=None,
        classify=None,
        explain=None,
    ):
        return original(
            session,
            message,
            reference_data,
            selected_detail_path=selected_detail_path,
            available_nodes=available_nodes,
            classify=fake_classify,
            explain=fake_explain,
        )

    monkeypatch.setattr(main, "handle_turn", patched)


def _start(**overrides):
    payload = {
        "current_major": "psychology_ba",
        "credits_completed": 72,
        "options": [
            {"major": "computer_science", "credits_transferable": 66},
            {"major": "information_technology", "credits_transferable": 69},
        ],
    }
    payload.update(overrides)
    return client.post(START, json=payload)


def test_one_request_runs_every_pairwise_comparison():
    response = _start()
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ready"
    assert len(body["comparison"]["options"]) == 2
    assert all(o["status"] == "calculated" for o in body["comparison"]["options"])


def test_start_returns_active_options_including_the_anchor():
    body = _start().json()
    assert body["state"]["active_options"] == [
        "psychology_ba",
        "computer_science",
        "information_technology",
    ]
    assert body["state"]["current_topic_scope"] == "broad"


def test_missing_transfer_figure_comes_back_pending_not_calculated():
    body = _start(
        options=[
            {"major": "computer_science", "credits_transferable": 66},
            {"major": "mechanical_energy_engineering"},
        ]
    ).json()

    by_key = {o["major_key"]: o for o in body["comparison"]["options"]}
    assert by_key["computer_science"]["status"] == "calculated"
    assert by_key["mechanical_energy_engineering"]["status"] == "pending"
    assert by_key["mechanical_energy_engineering"]["missing_fields"] == ["credits_transferable"]
    assert "dimensions" not in by_key["mechanical_energy_engineering"]


def test_transferable_exceeding_completed_fails_only_that_option():
    body = _start(
        options=[
            {"major": "computer_science", "credits_transferable": 66},
            {"major": "information_technology", "credits_transferable": 200},
        ]
    ).json()

    by_key = {o["major_key"]: o for o in body["comparison"]["options"]}
    assert by_key["computer_science"]["status"] == "calculated"
    assert by_key["information_technology"]["status"] == "failed"


def test_comparison_with_no_alternatives_is_rejected():
    response = _start(options=[{"major": "psychology_ba", "credits_transferable": 72}])
    assert response.status_code == 422
    assert "at least one alternative" in response.json()["detail"]["message"]


def test_topic_change_does_not_narrow_the_option_set():
    session_id = _start().json()["state"]["session_id"]

    body = client.post(
        ASK, json={"session_id": session_id, "message": "Which one costs more?"}
    ).json()

    assert body["status"] == "complete"
    assert body["state"]["current_topic_scope"] == "financial"
    assert len(body["state"]["active_options"]) == 3


def test_explicit_narrowing_changes_options_but_not_topic():
    session_id = _start(
        options=[
            {"major": "computer_science", "credits_transferable": 66},
            {"major": "information_technology", "credits_transferable": 69},
            {"major": "mechanical_energy_engineering", "credits_transferable": 54},
        ]
    ).json()["state"]["session_id"]

    client.post(ASK, json={"session_id": session_id, "message": "What about careers?"})
    body = client.post(
        ASK, json={"session_id": session_id, "message": "Just compare CS and IT"}
    ).json()

    assert body["state"]["current_topic_scope"] == "career"
    assert body["state"]["active_options"] == [
        "psychology_ba",
        "computer_science",
        "information_technology",
    ]


def test_preference_statement_leaves_the_comparison_alone():
    session_id = _start().json()["state"]["session_id"]

    body = client.post(
        ASK, json={"session_id": session_id, "message": "I'm leaning toward IT"}
    ).json()

    assert len(body["state"]["active_options"]) == 3


def test_verdict_question_returns_a_clarification():
    session_id = _start().json()["state"]["session_id"]

    body = client.post(
        ASK, json={"session_id": session_id, "message": "Which one is better?"}
    ).json()

    assert body["status"] == "clarification_required"
    assert "doesn't pick a winner" in body["message"]


def test_unknown_session_explains_the_in_memory_limitation():
    response = client.post(ASK, json={"session_id": "nope", "message": "hi"})
    assert response.status_code == 404
    assert "restarts" in response.json()["detail"]["message"]


def test_existing_pairwise_endpoints_still_work():
    """The whole point of building this additively."""
    response = client.post(
        "/decision-paths/change-major/calculate",
        json={
            "current_major": "psychology_ba",
            "prospective_major": "computer_science",
            "credits_completed": 72,
            "credits_transferable": 66,
        },
    )
    assert response.status_code == 200
    assert "summary" in response.json()
    assert response.json()["summary"]["current_major"] == "Psychology (B.A.)"


def test_health_still_fine():
    assert client.get("/health").json() == {"status": "ok"}


def teardown_module():
    SESSIONS._sessions.clear()
