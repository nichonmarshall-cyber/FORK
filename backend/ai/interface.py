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
from pydantic import BaseModel, Field, ValidationError

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


DECISION_QUESTION_SYSTEM_PROMPT = """You are Fork, a decision translator for a college student comparing two majors. You will be given a JSON object with a COMPLETE, ALREADY-CALCULATED comparison — summary figures, both paths compared, line items with sources and dates, career/earnings context, and stated assumptions and limitations — plus the student's question and which section of the decision map they currently have open.

You may ONLY reference numbers and facts present in that JSON object. Never calculate, estimate, or round anything differently than shown. Never introduce a fact, source, number, or citation that isn't in the object.

If the question isn't about this comparison (unrelated to major choice, credits, cost, timeline, or career outlook), set direct_answer to a brief redirect back to the decision and leave key_points, limitations, still_useful_for empty and next_step null.

The student currently has "{node_label}" open ({node_question}).

{question_focus}

RESPOND WITH ONLY a JSON object (no markdown fences, no other text) in exactly this shape:
{{
  "direct_answer": "1-3 sentences that directly answer the question. Never open with 'There are several things to consider', 'Based on the information provided', or 'It is important to note' -- start with the actual finding.",
  "key_points": [{{"title": "short title", "explanation": "plain-English explanation, referencing actual numbers/majors from the object"}}],
  "limitations": [{{"title": "short limitation", "explanation": "what the data cannot prove and why, in plain English"}}],
  "still_useful_for": ["one short phrase per thing this comparison IS still useful for"],
  "next_step": {{"action": "one concrete, practical action", "reason": "why it would improve the decision"}},
  "related_node_ids": ["zero or more ids from the list below that this answer specifically discusses"]
}}

next_step should be JSON null, not omitted, when no practical next step applies.

Valid node ids you may use in related_node_ids (nothing else): {node_id_list}

Ordering and priority rules:
- Order key_points and limitations by decision impact -- the single most important finding or limitation first. A shared-category earnings result matters more than "scholarships aren't included."
- Only include limitations, key_points, still_useful_for, or next_step that are actually relevant to THIS question -- omit a section entirely (empty list, or null for next_step) rather than padding it. Do not dump every possible disclaimer into every answer.
- Use plain English for technical terms: explain "federal earnings category" as "both majors are grouped together in the federal data," explain "differential fees" as "some programs charge extra fees," explain "incremental tuition" as "the estimated additional tuition from switching." Technical source names can still appear, but should not replace the plain-English explanation.
- Distinguish clearly between what Fork KNOWS (measured, sourced), what Fork ESTIMATES (a calculation with stated assumptions), and what Fork CANNOT DETERMINE (missing/suppressed data) -- use language like "Fork estimates," "the available data shows," "this does not prove," "an official what-if degree audit would confirm."

Rules that matter as much as the numbers:
- If a figure's status is "privacy_suppressed" or "unavailable", say it's missing and why -- never state or imply a number for it, and never call a missing comparison "no change" (that phrase means a real, measured zero difference, not an absence of data).
- College Scorecard earnings describe a group of graduates who received federal financial aid and were working and not enrolled when measured -- not every graduate, and not a personal prediction for this student. Say "graduates in this data," not "graduates" as if universal.
- Occupations connected to a major via the federal CIP-SOC crosswalk are occupations commonly related to that field of study, based on expert judgment -- NOT a record of where this program's actual graduates went to work. Never say a major "leads to" or "results in" these jobs.
- Never recommend switching or staying, and never claim more certainty than the sources support.

Keep the total response to roughly 120-250 words unless the question explicitly asks for a full breakdown."""

STRUCTURED_RETRY_SUFFIX = """

Your previous answer either wasn't valid JSON matching the required schema, or used a number that isn't in the JSON object you were given. Every number must come from that object -- copy figures rather than restating them from memory. Respond again with ONLY the valid JSON object in the exact schema requested, and if you're unsure a number is grounded, describe the finding in words instead of a number."""


# Maps keywords in the student's question to a focused instruction, so the
# five starter prompts (and similar free-text questions) get meaningfully
# different, targeted answers instead of the same general disclaimer every
# time. Checked in order; first match wins.
_QUESTION_FOCUS: list[tuple[tuple[str, ...], str]] = [
    (
        ("biggest difference", "biggest change", "most important", "most consequential"),
        "Focus on identifying the SINGLE most consequential difference between "
        "the two paths -- usually the largest dollar figure or the one with "
        "the least certainty behind it -- and explain why it matters more "
        "than the others.",
    ),
    (
        ("graduation", "longer", "semester", "timeline", "how long"),
        "Focus specifically on the credits and remaining semesters driving "
        "the graduation timeline. Explain what's causing any difference in "
        "time to finish; don't lead with cost or career figures.",
    ),
    (
        ("cost", "tuition", "afford", "expensive", "price", "money", "break down"),
        "Focus specifically on the tuition and cost figures: what's driving "
        "the additional cost, and what it doesn't account for (fees, "
        "financial aid, residency, program differential tuition).",
    ),
    (
        ("career", "job", "salary", "earn", "occupation", "outlook", "pay"),
        "Focus specifically on the earnings and career-outlook data: what "
        "it actually measures, its real limitations, and what it does not "
        "measure about this specific student's prospects.",
    ),
    (
        ("not tell", "don't know", "doesn't tell", "limitation", "can't", "cannot", "not know"),
        "Focus on identifying the most consequential gaps and limitations "
        "in this comparison -- what a student should NOT assume this data "
        "proves. This question is specifically about limitations, so "
        "limitations should be the largest section of the answer.",
    ),
]


def _question_focus(question: str) -> str:
    lowered = question.lower()
    for keywords, instruction in _QUESTION_FOCUS:
        if any(kw in lowered for kw in keywords):
            return instruction
    return (
        "Answer the specific question asked. Do not cover every section "
        "of the comparison -- only what's relevant to this question."
    )


class KeyPoint(BaseModel):
    title: str
    explanation: str


class Limitation(BaseModel):
    title: str
    explanation: str


class NextStep(BaseModel):
    action: str
    reason: str


class DecisionExplanation(BaseModel):
    """
    The structured shape every AI explanation takes, whether it came from
    the model or the deterministic fallback. One schema for both paths
    means main.py and the frontend never have to branch on which one
    produced a given answer.
    """
    direct_answer: str
    key_points: list[KeyPoint] = Field(default_factory=list)
    limitations: list[Limitation] = Field(default_factory=list)
    still_useful_for: list[str] = Field(default_factory=list)
    next_step: NextStep | None = None
    related_node_ids: list[str] = Field(default_factory=list)


def explain_decision(
    formatted_result: dict,
    question: str,
    node_id: str | None,
    node_label: str | None,
    node_question: str | None,
    available_nodes: list[dict] | None = None,
) -> dict:
    """
    Answers a follow-up question about an already-completed calculation
    with a structured explanation (direct answer, prioritized key points
    and limitations, what the comparison is still useful for, an optional
    next step, and which map nodes it touches on).

    available_nodes is the frontend's own list of {"id", "label"} for
    every node on the map -- used to (a) tell the model which node ids
    actually exist, and (b) filter its related_node_ids response against
    that same list afterward, so a model-invented id can never reach the
    frontend. Kept as the frontend's data rather than duplicated here, so
    there's exactly one place the map's node ids are defined.

    Returns {"explanation": DecisionExplanation, "used_fallback": bool}.
    """
    available_nodes = available_nodes or []
    available_ids = [n["id"] for n in available_nodes if "id" in n]
    node_id_list = ", ".join(available_ids) if available_ids else "(none provided)"

    system = DECISION_QUESTION_SYSTEM_PROMPT.format(
        node_label=node_label or "the overall comparison",
        node_question=node_question or "no specific question focused",
        question_focus=_question_focus(question),
        node_id_list=node_id_list,
    )
    user_message = json.dumps(
        {"calculation": formatted_result, "question": question, "selected_node_id": node_id}
    )

    result = _grounded_structured_explanation(system, user_message, formatted_result, available_ids)
    return {
        "explanation": result["explanation"],
        "used_fallback": result["used_fallback"],
    }


def _grounded_structured_explanation(
    system: str,
    user_message: str,
    formatted_result: dict,
    available_node_ids: list[str],
) -> dict:
    """
    Structured counterpart to _grounded_explanation (below, still used by
    explain_results/the /converse path): calls the model expecting the
    DecisionExplanation JSON schema, and on ANY failure -- invalid JSON,
    a schema mismatch, or a grounded-number check failing on the
    concatenation of every text field -- retries once with a stricter
    instruction, then falls back to a deterministic structured template
    if that also fails or the provider errors outright.
    """
    allowlist = _build_number_allowlist(formatted_result)

    def _attempt(sys_prompt: str) -> DecisionExplanation | None:
        try:
            raw = _call_model(sys_prompt, user_message, max_tokens=900)
        except Exception:
            return None
        explanation = _parse_structured_explanation(raw)
        if explanation is None:
            return None
        if not _all_numbers_grounded(_explanation_text_for_grounding(explanation), allowlist):
            return None
        explanation.related_node_ids = _filter_to_known_nodes(
            explanation.related_node_ids, available_node_ids
        )
        return explanation

    first = _attempt(system)
    if first is not None:
        return {"explanation": first, "used_fallback": False}

    second = _attempt(system + STRUCTURED_RETRY_SUFFIX)
    if second is not None:
        return {"explanation": second, "used_fallback": False}

    return {
        "explanation": _fallback_explanation_structured(formatted_result),
        "used_fallback": True,
    }


def _parse_structured_explanation(raw: str) -> DecisionExplanation | None:
    """Returns None rather than raising on anything that isn't valid JSON
    matching the schema -- invalid provider output is exactly the case
    meant to trigger a retry or fallback, not an exception."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    try:
        return DecisionExplanation.model_validate(data)
    except ValidationError:
        return None


def _filter_to_known_nodes(node_ids: list[str], available_node_ids: list[str]) -> list[str]:
    """Never trust the model's related_node_ids blindly -- an id that
    doesn't exist on the map would break the frontend's 'open this node'
    action, or could reference something invented. Anything not in the
    caller-supplied list is silently dropped rather than failing the
    whole answer over a bad reference."""
    allowed = set(available_node_ids)
    return [n for n in node_ids if n in allowed]


def _explanation_text_for_grounding(exp: DecisionExplanation) -> str:
    """Concatenates every user-visible text field so the existing,
    already-tested number-grounding check can run against the whole
    structured answer, not just a single paragraph."""
    parts = [exp.direct_answer]
    for kp in exp.key_points:
        parts.append(kp.title)
        parts.append(kp.explanation)
    for lim in exp.limitations:
        parts.append(lim.title)
        parts.append(lim.explanation)
    parts.extend(exp.still_useful_for)
    if exp.next_step:
        parts.append(exp.next_step.action)
        parts.append(exp.next_step.reason)
    return " ".join(parts)


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


def _fallback_explanation_structured(formatted_result: dict) -> DecisionExplanation:
    """
    Structured counterpart to _fallback_explanation: same true facts, same
    "built entirely from string formatting, nothing here could be
    invented" guarantee, just organized into the DecisionExplanation
    schema instead of one paragraph. Used when the model can't produce a
    valid, grounded structured answer twice in a row, or the provider
    itself fails outright.
    """
    summary = formatted_result.get("summary", {})
    cur = summary.get("current_major", "your current major")
    pro = summary.get("prospective_major", "the major you're considering")

    cost = summary.get("incremental_total_cost")
    semesters = summary.get("incremental_semesters")
    delta = summary.get("annual_salary_delta")

    if cost is not None and cost != 0:
        direction = "more" if cost > 0 else "less"
        direct_answer = (
            f"Switching from {cur} to {pro} is projected to cost "
            f"{_money(abs(cost))} {direction} overall, based on your reported credits."
        )
    else:
        direct_answer = (
            f"Here's what the numbers show for {cur} vs. {pro}, based on your reported credits."
        )

    key_points: list[KeyPoint] = []
    if semesters is not None:
        if semesters > 0:
            key_points.append(
                KeyPoint(
                    title="Longer time to graduate",
                    explanation=f"This path is projected to take {semesters} more semester(s).",
                )
            )
        elif semesters < 0:
            key_points.append(
                KeyPoint(
                    title="Shorter time to graduate",
                    explanation=f"This path is projected to take {abs(semesters)} fewer semester(s).",
                )
            )
        else:
            key_points.append(
                KeyPoint(
                    title="No change to graduation timeline",
                    explanation="Time to graduate isn't projected to change.",
                )
            )

    limitations: list[Limitation] = []
    if delta is None:
        limitations.append(
            Limitation(
                title="Earnings couldn't be compared",
                explanation=(
                    "At least one major's earnings figure isn't available in the "
                    "data Fork has, so a career-outlook comparison can't be made here."
                ),
            )
        )
    elif delta == 0:
        key_points.append(
            KeyPoint(
                title="No measured earnings difference",
                explanation="Reported early-career earnings are the same for both, based on the available data.",
            )
        )
    else:
        direction = "more" if delta > 0 else "less"
        key_points.append(
            KeyPoint(
                title="Earnings difference",
                explanation=f"Reported early-career earnings differ by {_money(abs(delta))}/yr {direction}.",
            )
        )

    return DecisionExplanation(
        direct_answer=direct_answer,
        key_points=key_points,
        limitations=limitations,
        still_useful_for=[
            "Comparing the estimated tuition and timeline impact of switching",
        ],
        next_step=None,
        related_node_ids=[],
    )