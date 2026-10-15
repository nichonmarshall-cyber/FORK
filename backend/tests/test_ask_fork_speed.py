"""
Ask Fork's latency safeguards.

Each test pins down one way a question used to cost more model calls, or
more waiting, than it needed to.
"""

import json
import re
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from tests.test_main import (
    _EXPLAIN_BODY,
    _GOOD_EXPLAIN_JSON,
    _dispatch,
    _fail_everything,
)

client = TestClient(app)
TYPED = {**_EXPLAIN_BODY, "question": "how much more would switching cost me?"}


def _ask(body, side_effect):
    with patch("ai.interface._call_model") as mock_call:
        mock_call.side_effect = side_effect
        res = client.post("/decision-paths/change-major/explain", json=body)
    return res, mock_call


def test_a_chip_makes_one_model_call_and_a_typed_question_two():
    res, calls = _ask(_EXPLAIN_BODY, _dispatch(_GOOD_EXPLAIN_JSON))
    assert res.json()["status"] == "complete"
    assert calls.call_count == 1  # explanation only

    res, calls = _ask(TYPED, _dispatch(_GOOD_EXPLAIN_JSON))
    assert res.json()["status"] == "complete"
    assert calls.call_count == 2  # classify, then explain


def test_the_same_question_on_the_same_calculation_is_answered_from_cache():
    first, _ = _ask(_EXPLAIN_BODY, _dispatch(_GOOD_EXPLAIN_JSON))
    second, calls = _ask(_EXPLAIN_BODY, _dispatch(_GOOD_EXPLAIN_JSON))
    assert calls.call_count == 0
    assert second.headers.get("X-Fork-Answer-Cache") == "hit"
    assert second.json()["direct_answer"] == first.json()["direct_answer"]

    # A different calculation is a different answer.
    other = {**_EXPLAIN_BODY, "credits_transferable": _EXPLAIN_BODY["credits_transferable"] - 6}
    _, calls = _ask(other, _dispatch(_GOOD_EXPLAIN_JSON))
    assert calls.call_count == 1


def test_a_fallback_answer_is_not_cached():
    _ask(_EXPLAIN_BODY, _dispatch(RuntimeError("overloaded")))
    res, calls = _ask(_EXPLAIN_BODY, _dispatch(_GOOD_EXPLAIN_JSON))
    assert calls.call_count == 1
    assert res.json()["used_fallback"] is False


def test_provider_failures_are_not_retried_by_the_app():
    """The SDK retries rate limits and outages itself. The app adding its
    own retry on top only doubled the wait before the same outcome."""
    _, calls = _ask(TYPED, _fail_everything)
    assert calls.call_count == 1  # one classifier attempt, then "unavailable"


def test_a_malformed_answer_is_still_retried_once():
    _, calls = _ask(_EXPLAIN_BODY, _dispatch("not json"))
    assert calls.call_count == 2


def test_timings_are_exposed_in_a_server_timing_header():
    res, _ = _ask(TYPED, _dispatch(_GOOD_EXPLAIN_JSON))
    header = res.headers.get("Server-Timing", "")
    assert re.search(r"intent;dur=\d+", header)
    assert re.search(r"explain;dur=\d+", header)


def test_streaming_sends_real_stages_then_the_same_answer():
    with patch("ai.interface._call_model") as mock_call:
        mock_call.side_effect = _dispatch(_GOOD_EXPLAIN_JSON)
        plain = client.post("/decision-paths/change-major/explain", json=TYPED).json()
    from ai import answer_cache

    answer_cache.clear()
    with patch("ai.interface._call_model") as mock_call:
        mock_call.side_effect = _dispatch(_GOOD_EXPLAIN_JSON)
        res = client.post("/decision-paths/change-major/explain/stream", json=TYPED)
    assert res.headers["content-type"].startswith("text/event-stream")
    events = [
        (block.split("\n")[0].removeprefix("event: "), json.loads(block.split("\n")[1].removeprefix("data: ")))
        for block in res.text.strip().split("\n\n")
    ]
    stages = [d for k, d in events if k == "stage"]
    assert stages == ["received", "understanding", "writing", "checking"]
    kind, result = events[-1]
    assert kind == "result"
    plain.pop("state"), result.pop("state")
    assert result == plain


def test_streaming_reports_a_rewrite_when_the_checker_rejects_an_answer():
    bad = json.dumps({**json.loads(_GOOD_EXPLAIN_JSON), "direct_answer": "It costs $123,456,789 more."})
    answers = iter([bad, _GOOD_EXPLAIN_JSON])

    def side_effect(system, user_message, max_tokens=1024, model=None):
        return next(answers)

    with patch("ai.interface._call_model", side_effect=side_effect):
        res = client.post("/decision-paths/change-major/explain/stream", json=_EXPLAIN_BODY)
    stages = re.findall(r'event: stage\ndata: "(\w+)"', res.text)
    assert stages == ["received", "writing", "checking", "rewriting", "checking"]
    assert '"used_fallback": false' in res.text


def test_streaming_passes_errors_through():
    body = {**_EXPLAIN_BODY, "institution_id": "nowhere"}
    res = client.post("/decision-paths/change-major/explain/stream", json=body)
    assert "event: error" in res.text and '"status_code": 404' in res.text


def test_client_has_a_timeout_and_a_single_retry(monkeypatch):
    import ai.interface as ai

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ai, "_client", None)
    c = ai._get_client()
    assert c.max_retries == 1
    assert c.timeout.read == 30.0
    monkeypatch.setattr(ai, "_client", None)


def test_chip_list_matches_the_frontend():
    from conversation.presets import PRESET_TOPICS

    source = (
        Path(__file__).resolve().parents[2] / "frontend/components/chat/DecisionChat.tsx"
    ).read_text(encoding="utf-8")
    block = source[source.index("const SUGGESTED_QUESTIONS") :]
    block = block[: block.index("];")]
    assert set(re.findall(r'"([^"]+)"', block)) == set(PRESET_TOPICS)
