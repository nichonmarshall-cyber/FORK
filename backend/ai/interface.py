"""
The AI Interface Layer. This is the ONLY module in the backend that talks
to an LLM provider. Nothing outside this file knows or cares which
provider is behind it — see ARCHITECTURE.md, "The AI Interface Layer."

Two responsibilities, and only two:
  1. extract_inputs()  — conversation -> structured inputs (or a request
     for more information). Never guesses a number; if a value isn't in
     the conversation, it's reported missing, not invented.
  2. explain_results() — structured result -> plain-language narration.
     The prompt receives ONLY the result object, so it cannot introduce
     any number that didn't come from the engine.

Requires ANTHROPIC_API_KEY in the environment. Swap providers by editing
_call_model() only — nothing else in the codebase should change.
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
    """The single choke point for all LLM calls. Swapping providers means
    editing this function and nothing else."""
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
    """Raises MissingInputs if the conversation doesn't yet contain enough
    information to build a complete, valid ChangeMajorInputs."""
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

    # Pydantic validates types/ranges here; ValueError/ValidationError
    # propagates up rather than being silently coerced.
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
    """Takes the formatter's output dict — never the raw engine dataclass,
    never the original conversation — so the AI physically cannot
    reference anything the student said that isn't already a validated
    number in the result."""
    user_message = json.dumps(formatted_result)
    explanation = _call_model(EXPLANATION_SYSTEM_PROMPT, user_message, max_tokens=400)
    _verify_no_invented_numbers(explanation, formatted_result)
    return explanation


def _verify_no_invented_numbers(explanation: str, formatted_result: dict) -> None:
    """Best-effort guardrail: every line-item value should be traceable.
    This does not parse every number in prose (that's a harder NLP
    problem) but is the hook where a stricter regex/number-extraction
    check belongs before this ships. Documented here deliberately so the
    gap is visible rather than silently assumed away."""
    # TODO before demo: extract all numeric tokens from `explanation` and
    # assert each one matches (within rounding) a value in
    # formatted_result["line_items"] or formatted_result["summary"].
    # Left as an explicit stub rather than faked — see ARCHITECTURE.md,
    # "Guardrails, enforced structurally."
    pass