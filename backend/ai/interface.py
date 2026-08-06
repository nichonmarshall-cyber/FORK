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
import re

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
3-5 short sentences.

Rules that matter as much as the numbers:
- If a figure's status is "privacy_suppressed" or "unavailable", say it's \
missing and why — never state or imply a number for it, and never call a \
missing comparison "no change" (that phrase means a real, measured zero \
difference, not an absence of data).
- College Scorecard earnings describe a group of graduates who received \
federal financial aid and were working and not enrolled when measured — \
not every graduate of the program. Say "graduates in this data" or \
similar, not "graduates" as if it were universal.
- Occupations connected to a major via the federal CIP-SOC crosswalk are \
occupations commonly related to that field of study, based on expert \
judgment — NOT a record of where this program's actual graduates went to \
work. Never say a major "leads to" or "results in" these jobs.
- Never recommend switching or staying. Describe; don't decide for them.
"""

STRICT_RETRY_SUFFIX = """

Your previous answer used a number that isn't in the JSON object you were \
given. Every number in your answer must come from that object — copy \
figures rather than restating them from memory, and if you're unsure a \
number is grounded, describe the finding in words instead of a number."""


def explain_results(formatted_result: dict) -> str:
    """Receives only the formatter's dict — not the engine objects, not the
    original message. So it has no way to reference something the student
    said that didn't become a validated number."""
    result = _grounded_explanation(
        EXPLANATION_SYSTEM_PROMPT, json.dumps(formatted_result), formatted_result
    )
    return result["text"]


DECISION_QUESTION_SYSTEM_PROMPT = """You answer a student's question about \
a Change Major financial comparison that has ALREADY been calculated. You \
will be given a JSON object with the full result — summary figures, both \
paths compared, line items with sources and dates, career/earnings \
context, and stated assumptions and limitations — plus the student's \
question and which node of the decision map they currently have open.

You may ONLY reference numbers and facts present in that JSON object. Do \
not calculate anything new — every figure you state must be copied from \
the object, not derived, estimated, or rounded differently than shown. \
Do not introduce a fact, source, or number that isn't in the object.

If the student's question isn't about this comparison — asks something \
unrelated to their major choice, credits, cost, timeline, or career \
outlook — say so briefly and invite them to ask about the decision \
instead. Do not answer unrelated questions even partially.

The student currently has the "{node_label}" section of the map open \
({node_question}). Prioritize information relevant to that section, but \
you may reference other parts of the object if the question needs it — \
e.g. "the biggest difference" may span more than one section.

Rules that matter as much as the numbers:
- If a figure's status is "privacy_suppressed" or "unavailable", say it's \
missing and why — never state or imply a number for it, and never call a \
missing comparison "no change" (that phrase means a real, measured zero \
difference, not an absence of data).
- College Scorecard earnings describe a group of graduates who received \
federal financial aid and were working and not enrolled when measured — \
not every graduate of the program. Say "graduates in this data" or \
similar, not "graduates" as if it were universal.
- Occupations connected to a major via the federal CIP-SOC crosswalk are \
occupations commonly related to that field of study, based on expert \
judgment — NOT a record of where this program's actual graduates went to \
work. Never say a major "leads to" or "results in" these jobs.
- Never recommend switching or staying, and never claim more certainty \
than the sources support. Describe what the data shows; let the student \
decide.

Give a short, direct answer first (1-2 sentences), then optional \
supporting detail (1-3 more sentences) if it helps. Plain language, no \
jargon, no field names like "EARN_MDN_1YR" or raw CIP/SOC codes."""


def explain_decision(
    formatted_result: dict,
    question: str,
    node_id: str | None,
    node_label: str | None,
    node_question: str | None,
) -> dict:
    """
    Answers a follow-up question about an already-completed calculation.

    Returns a dict rather than a bare string so the caller can distinguish
    a real answer from a redirect (off-topic question) and from a
    fallback (grounding failed twice) — the frontend shows each of those
    slightly differently, and main.py shouldn't have to parse prose to
    tell them apart.
    """
    system = DECISION_QUESTION_SYSTEM_PROMPT.format(
        node_label=node_label or "the overall comparison",
        node_question=node_question or "no specific question focused",
    )
    user_message = json.dumps(
        {"calculation": formatted_result, "question": question, "selected_node_id": node_id}
    )

    answer = _grounded_explanation(system, user_message, formatted_result)
    return {
        "answer": answer["text"],
        "grounded": answer["grounded"],
        "used_fallback": answer["used_fallback"],
    }


def _grounded_explanation(system: str, user_message: str, formatted_result: dict) -> dict:
    """
    The actual enforcement loop: call the model, verify every number it
    used against the calculation, retry once with a stricter instruction
    if verification fails, and fall back to a deterministic template
    (built from string formatting, not a model call — cannot invent
    anything) if the retry still fails.

    Returns {"text": str, "grounded": bool, "used_fallback": bool} so
    callers know which path produced the answer, not just the text.
    """
    allowlist = _build_number_allowlist(formatted_result)

    try:
        first = _call_model(system, user_message, max_tokens=400)
    except Exception:
        # Provider failure (network, auth, rate limit, timeout — anything
        # anthropic's client can raise). Never let a raw provider
        # exception reach the API layer; the fallback is always safe.
        return {
            "text": _fallback_explanation(formatted_result),
            "grounded": True,
            "used_fallback": True,
        }

    if _all_numbers_grounded(first, allowlist):
        return {"text": first, "grounded": True, "used_fallback": False}

    try:
        second = _call_model(system + STRICT_RETRY_SUFFIX, user_message, max_tokens=400)
    except Exception:
        return {
            "text": _fallback_explanation(formatted_result),
            "grounded": True,
            "used_fallback": True,
        }

    if _all_numbers_grounded(second, allowlist):
        return {"text": second, "grounded": True, "used_fallback": False}

    return {
        "text": _fallback_explanation(formatted_result),
        "grounded": True,
        "used_fallback": True,
    }


# --- grounding: allowlist construction ---------------------------------

_NUMBER_TOKEN_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _numeric_variants(n: float) -> set[str]:
    """
    A model describing a real figure won't necessarily reproduce it
    byte-for-byte — it might round $19,347.33 to "$19,347", drop the
    minus sign and say "less" instead, or write "0.8" as "0.80". None of
    that is invention; it's paraphrase of a real number. This generates
    the set of strings that should all count as "the same number" for
    grounding purposes, so the check is strict about NEW numbers without
    being strict about formatting.
    """
    variants = set()
    for value in (n, abs(n), round(n), round(abs(n)), round(n, 1), round(abs(n), 1)):
        if isinstance(value, float) and value.is_integer():
            variants.add(str(int(value)))
        else:
            variants.add(str(value))
        variants.add(f"{value:.2f}".rstrip("0").rstrip("."))
    return variants


def _build_number_allowlist(value, out: set[str] | None = None) -> set[str]:
    """
    Recursively walks the calculation dict and collects every number that
    would be legitimate for an explanation to mention — including numbers
    embedded inside string fields (source names, dates, assumptions,
    limitations), since real facts like "15 credits per semester" or a
    CIP code or a dataset year live in prose, not just in numeric JSON
    leaves.
    """
    if out is None:
        out = set()

    if isinstance(value, bool):
        pass  # bool is a subclass of int; explicitly skip so True/False don't become "1"/"0"
    elif isinstance(value, (int, float)):
        out.update(_numeric_variants(float(value)))
    elif isinstance(value, str):
        for match in _NUMBER_TOKEN_RE.finditer(value):
            token = match.group().replace(",", "")
            try:
                out.update(_numeric_variants(float(token)))
            except ValueError:
                pass
    elif isinstance(value, dict):
        for v in value.values():
            _build_number_allowlist(v, out)
    elif isinstance(value, list):
        for v in value:
            _build_number_allowlist(v, out)

    return out


def _all_numbers_grounded(text: str, allowlist: set[str]) -> bool:
    """True only if every numeric token in `text` traces back to the
    allowlist. A response with no numbers at all is trivially grounded —
    plenty of good answers don't need to cite a figure."""
    for match in _NUMBER_TOKEN_RE.finditer(text):
        token = match.group().replace(",", "")
        try:
            value = float(token)
        except ValueError:
            continue
        if not (_numeric_variants(value) & allowlist):
            return False
    return True


# --- deterministic fallback: pure string formatting, cannot invent ------


def _money(n: float) -> str:
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):,.0f}"


def _fallback_explanation(formatted_result: dict) -> str:
    """
    Built entirely from string formatting against the calculation dict —
    no model call, so there's nothing here that could be invented. Used
    when the AI can't produce a grounded answer twice in a row. Deliberately
    plain and a little generic; the priority is that everything it says is
    true, not that it's especially insightful.
    """
    summary = formatted_result.get("summary", {})
    cur = summary.get("current_major", "your current major")
    pro = summary.get("prospective_major", "the major you're considering")

    lines = [f"Here's what the numbers show for {cur} vs. {pro}, based on your reported credits."]

    cost = summary.get("incremental_total_cost")
    if cost is not None:
        direction = "more" if cost > 0 else "less" if cost < 0 else "the same"
        lines.append(
            f"Switching is projected to cost {_money(abs(cost))} {direction} overall."
            if cost != 0
            else "Switching is projected to cost about the same overall."
        )

    semesters = summary.get("incremental_semesters")
    if semesters is not None:
        if semesters > 0:
            lines.append(f"It's projected to take {semesters} more semester(s).")
        elif semesters < 0:
            lines.append(f"It's projected to take {abs(semesters)} fewer semester(s).")
        else:
            lines.append("Time to graduate isn't projected to change.")

    delta = summary.get("annual_salary_delta")
    if delta is None:
        lines.append(
            "Early-career earnings couldn't be compared — at least one figure isn't available."
        )
    elif delta == 0:
        lines.append("Reported early-career earnings are the same for both.")
    else:
        direction = "more" if delta > 0 else "less"
        lines.append(f"Reported early-career earnings differ by {_money(abs(delta))}/yr {direction}.")

    lines.append("See the numbers above for the full breakdown and sources.")
    return " ".join(lines)