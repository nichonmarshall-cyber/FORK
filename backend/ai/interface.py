"""
The only module here that talks to an LLM. Nothing else imports anthropic.

Two responsibilities:
  1. extract_inputs()  — read what someone wrote and pull out the fields.
     If a value isn't there, report it missing rather than inventing it.
  2. explain_results() — take the finished numbers and write them up in
     plain language. Only receives the result object, so it can't reference
     a figure that didn't come out of the engine.

Requires ANTHROPIC_API_KEY in the environment (.env works). Switching
providers means editing _call_model() and nothing else.
"""

import json
import os

import anthropic

from decision_paths.change_major.inputs import ChangeMajorInputs, MissingInputs

_MODEL = "claude-sonnet-4-6"

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Export it before running the "
                "server: export ANTHROPIC_API_KEY=sk-ant-..."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _call_model(system: str, user_message: str, max_tokens: int = 1024) -> str:
    """Every LLM call goes through here, so switching providers means
    changing this one function."""
    client = _get_client()
    response = client.messages.create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


EXTRACTION_SYSTEM_PROMPT = """You extract structured data from a student's \
message about changing their college major. You do not calculate anything, \
you do not estimate anything, and you do not recommend anything. You only \
identify what the student has told you and map it to fields.

Valid major keys are exactly: computer_science, information_technology, \
business_administration, psychology, nursing, mechanical_engineering.

Respond with ONLY a JSON object, no other text, no markdown fences, in \
this exact shape:

{
  "current_major": "<major key or null if not stated>",
  "prospective_major": "<major key or null if not stated>",
  "credits_completed": <integer or null if not stated>,
  "credits_transferable": <integer or null if not stated>,
  "missing_fields": ["<list of field names above that are null>"]
}

If the student names a major that isn't in the valid key list, treat it as \
null and add "current_major" or "prospective_major" to missing_fields — do \
not guess the closest match. If the student doesn't state how many of their \
credits transfer, that field is null; never assume all or none transfer."""


def extract_inputs(conversation_text: str) -> ChangeMajorInputs:
    """Raises MissingInputs if the message doesn't contain enough yet to
    build a complete set of valid inputs."""
    raw = _call_model(EXTRACTION_SYSTEM_PROMPT, conversation_text)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"AI extraction did not return valid JSON: {raw!r}") from e

    missing = [k for k in
               ["current_major", "prospective_major", "credits_completed", "credits_transferable"]
               if parsed.get(k) is None]
    if missing:
        raise MissingInputs(missing)

    # Pydantic validates types and ranges here. Let it raise rather than
    # quietly coercing a bad value into a plausible one.
    return ChangeMajorInputs(
        current_major=parsed["current_major"],
        prospective_major=parsed["prospective_major"],
        credits_completed=parsed["credits_completed"],
        credits_transferable=parsed["credits_transferable"],
    )


EXPLANATION_SYSTEM_PROMPT = """You explain a financial projection to a \
college student in plain, warm, direct language. You will be given a JSON \
result object. You may ONLY reference numbers and facts present in that \
object. Do not perform any arithmetic of your own, do not introduce any \
figure not present in the object, and do not tell the student what they \
should do — describe what the numbers show and let them decide. Keep it to \
3-5 short sentences."""


def explain_results(formatted_result: dict) -> str:
    """Receives only the formatter's dict — not the engine objects, not the
    original message. So it has no way to reference something the student
    said that didn't become a validated number."""
    user_message = json.dumps(formatted_result)
    explanation = _call_model(EXPLANATION_SYSTEM_PROMPT, user_message, max_tokens=400)
    _verify_no_invented_numbers(explanation, formatted_result)
    return explanation


def _verify_no_invented_numbers(explanation: str, formatted_result: dict) -> None:
    """Meant to verify the AI didn't invent a number. Currently doesn't.

    TODO before the demo: extract every numeric token from `explanation`
    and confirm each one appears somewhere in formatted_result, within
    rounding. Regenerate the explanation if any don't.

    Left as a visible stub rather than quietly removed, because "the AI
    can't fabricate a number" is the core claim of this project and right
    now it's enforced by the prompt asking, not by code checking. Known
    gap, documented on purpose.
    """
    pass
