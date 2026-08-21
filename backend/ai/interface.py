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
import logging
import os
import re
from typing import Literal

import anthropic
from pydantic import BaseModel, Field, ValidationError

from decision_paths.change_major.inputs import ChangeMajorInputs, MissingInputs

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"

# Kept as two names, currently pointing at the same model, so the intent
# classifier and the explanation writer can move to different models later
# without touching call sites -- see ai/interface.py's module docstring
# addition below.
INTENT_MODEL = _MODEL
EXPLANATION_MODEL = _MODEL

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


def _call_model(
    system: str, user_message: str, max_tokens: int = 1024, model: str = EXPLANATION_MODEL
) -> str:
    """Every LLM call goes through here, so switching providers means
    changing this one function."""
    client = _get_client()
    response = client.messages.create(
        model=model,
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

You may restate and explain a relationship the object already contains (e.g. the object's own annual_salary_delta, or a stated percent-growth figure from BLS data). You may NOT create a NEW mathematical relationship between two values that weren't already compared by the backend. This specifically means never writing any of the following, even approximately or hedged with "roughly" or "theoretically":
- a ratio or multiplier between two figures ("X times larger/more/higher than", "5x the cost")
- a percent comparison you computed yourself ("43% higher than", "a 20% increase over")
- a payback period, break-even point, or "recovered/paid off/earned back in X years/months"
- return on investment, ROI, or "makes financial sense"
- a claim that switching is "worth it," "worth the cost," or similar
- any per-month or per-week figure derived from an annual or per-semester one, or vice versa, unless that exact figure already appears in the object

If a comparison like this would be useful, describe the two figures side by side in plain language instead ("Computer Science graduates report $70,235; Psychology graduates report $30,396") and let the student draw their own conclusion — do not draw it for them.

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

Each section must do a DIFFERENT job. Do not restate the same finding in more than one section unless the later mention adds materially new information -- a limitation, a source explanation, a distinct engine result, or a concrete action. Before writing a key point, ask "what new information does this add?" If the answer is "none", leave it out. Two good points beat three where the third repeats the first; one is fine if that's all there genuinely is.

Let the QUESTION decide what you emphasize. A tuition question gets tuition; a credits question gets credit applicability and its uncertainty; an earnings question gets earnings data and its limits. If career data is unavailable, say so plainly rather than filling the space with generic career language. If no single factor clearly separates the two options, say that -- "No single factor clearly separates the two options in the current comparison" is a valid and honest answer. Do not force every response into a "biggest difference" shape.

Be precise about how certain each statement is:
- KNOWN: directly supported by trusted source data ("The College Scorecard data reports...")
- CALCULATED: explicitly returned by the deterministic engine ("Fork calculates...")
- ESTIMATED: computed using assumptions or values the student typed in ("Fork currently estimates...")
- UNRESOLVED: cannot be confirmed without outside verification ("An official degree audit could confirm...")

CREDIT TRANSFER WORDING. The transferable-credit count is something the student typed, not an official audit. Write "Based on the information you entered, 66 of your 72 completed credits are currently counted toward the prospective degree" or "Fork currently estimates that 6 credits may not apply toward the prospective degree." NEVER write that credits are "wasted", "lost", "count toward nothing", "have no value", "permanently lost", or "definitely do not transfer" -- those state as fact something only a what-if degree audit can determine, and unapplied credits often still satisfy electives.

EARNINGS WORDING. Scorecard figures describe a group of past graduates, never a personal prediction. When the federal category is broader than the specific major, name the category, not the major: write "the available College Scorecard data reports $70,235 for the broader Computer and Information Sciences graduate group", not "Computer Science graduates make $70,235". A one-year-after-graduation figure is a single snapshot -- never claim the difference recurs annually, persists, or compounds.

RELATED NODES: pick roughly 1-3 that the answer genuinely discusses, not everything technically connected. An earnings answer might link salary and career nodes; a graduation-delay answer might link credit transfer, time to graduate, and tuition.

Keep the total response to roughly 120-250 words unless the question explicitly asks for a full breakdown."""

STRUCTURED_RETRY_SUFFIX = """

Your previous answer either wasn't valid JSON matching the required schema, or used a number that isn't in the JSON object you were given. Every number must come from that object -- copy figures rather than restating them from memory. Respond again with ONLY the valid JSON object in the exact schema requested, and if you're unsure a number is grounded, describe the finding in words instead of a number."""

RELATIONSHIP_RETRY_SUFFIX = """

Your previous answer stated a mathematical relationship between two figures that the backend never computed -- a ratio, multiplier, percent comparison, payback period, break-even claim, ROI, or a "worth it" judgment. Every one of those requires arithmetic Fork's engine did not perform. Respond again with ONLY the valid JSON object, describing the relevant figures side by side in plain language instead of comparing them with a ratio, percentage, timeframe, or verdict you compute yourself."""


# The single focus-instruction table shared by both Compare One (/explain)
# and Compare Multiple (/comparison/ask). Which entry applies comes from
# the AI intent classifier's topic_scope (see classify_intent(), below) --
# not from keyword matching against the question text. This is what
# replaced the old per-endpoint keyword tables (_QUESTION_FOCUS here and
# router.py's _TOPIC_KEYWORDS): one classification step, two callers, no
# phrase list to keep growing.
_TOPIC_FOCUS_INSTRUCTIONS: dict[str, str] = {
    "broad": (
        "Answer the specific question asked. If it asks for the single "
        "biggest difference, identify the most consequential one and say "
        "why it matters more than the others. If it specifically asks what "
        "the data does NOT show, lead with limitations rather than "
        "repeating figures already on screen. Otherwise synthesize the "
        "meaningful tradeoffs across whatever dimensions are present -- you "
        "do not need to mechanically list every figure; where things barely "
        "differ, say so briefly and move on."
    ),
    "financial": (
        "Focus on the tuition and total-cost figures: what's driving the "
        "additional cost, and what it doesn't account for (fees, financial "
        "aid, residency, program differential tuition). Early-career "
        "earnings figures may be cited if they bear on the financial "
        "picture, but don't lead with them and don't turn this into a "
        "career-outlook answer -- job-market or occupation data is out of "
        "scope here."
    ),
    "timeline": (
        "Focus specifically on the credits and remaining semesters driving "
        "the graduation timeline. Explain what's causing any difference in "
        "time to finish; don't lead with cost or career figures."
    ),
    "credits": (
        "Focus on what applies where, what's still needed, and how "
        "uncertain those figures are without an official audit."
    ),
    "career": (
        "Focus specifically on the earnings and career-outlook data: what "
        "it actually measures, its real limitations, and what it does not "
        "measure about this specific student's prospects. Don't bring in "
        "cost or timeline figures."
    ),
}


def _topic_focus_instruction(topic_scope: str) -> str:
    return _TOPIC_FOCUS_INSTRUCTIONS.get(topic_scope, _TOPIC_FOCUS_INSTRUCTIONS["broad"])


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
    topic_scope: str = "broad",
) -> dict:
    """
    Answers a follow-up question about an already-completed calculation
    with a structured explanation (direct answer, prioritized key points
    and limitations, what the comparison is still useful for, an optional
    next step, and which map nodes it touches on).

    `topic_scope` comes from classify_intent() -- resolved once, upstream,
    by the same intent classifier Compare Multiple uses -- and only ever
    selects a focus INSTRUCTION here (see _topic_focus_instruction()).
    Compare One doesn't gate which data the model can see by scope the way
    Compare Multiple's build_view() does: a pairwise CalcResult only ever
    describes the two majors already fully authorized for this
    conversation, so there's no cross-option leakage risk to guard
    against, and adding one would be new machinery for a problem that
    doesn't exist here.

    available_nodes is the frontend's own list of {"id", "label"} for
    every node on the map -- used to (a) tell the model which node ids
    actually exist, and (b) filter its related_node_ids response against
    that same list afterward, so a model-invented id can never reach the
    frontend. Kept as the frontend's data rather than duplicated here, so
    there's exactly one place the map's node ids are defined.

    Returns {"explanation": DecisionExplanation, "used_fallback": bool,
    "topic_scope": str}.
    """
    available_nodes = available_nodes or []
    available_ids = [n["id"] for n in available_nodes if "id" in n]
    node_id_list = ", ".join(available_ids) if available_ids else "(none provided)"

    system = DECISION_QUESTION_SYSTEM_PROMPT.format(
        node_label=node_label or "the overall comparison",
        node_question=node_question or "no specific question focused",
        question_focus=_topic_focus_instruction(topic_scope),
        node_id_list=node_id_list,
    )
    user_message = json.dumps(
        {"calculation": formatted_result, "question": question, "selected_node_id": node_id}
    )

    result = _grounded_structured_explanation(system, user_message, formatted_result, available_ids)
    return {
        "explanation": result["explanation"],
        "used_fallback": result["used_fallback"],
        "topic_scope": topic_scope,
    }


# --- derived-relationship guard -----------------------------------------
#
# Numeric grounding alone isn't enough: two individually real figures can
# each pass that check while their RELATIONSHIP is invented by the model
# ("$39,839 is roughly five times larger than $8,498" — both dollar
# amounts are grounded; "five times larger" is arithmetic Fork never
# performed). This is a second, independent check for exactly that
# failure mode, working alongside the system prompt's own instructions
# rather than replacing them — the prompt is the first line of defense,
# this is the one that doesn't depend on the model actually listening.

# Phrases that are NEVER legitimate regardless of what numbers surround
# them, because the backend has no field that computes any of these
# concepts at all — their mere presence means the model invented them.
_ALWAYS_BANNED_PATTERNS = [
    re.compile(r"\bpays?\s+for\s+itself\b", re.I),
    re.compile(r"\bpays?\s+off\b", re.I),
    re.compile(r"\bbreak[\s-]?even\b", re.I),
    re.compile(r"\brecoup(s|ed|ing)?\b", re.I),
    re.compile(r"\brecover(s|ed|ing)?\s+(the\s+)?(switching\s+)?cost", re.I),
    re.compile(r"\bmakes?\s+(it|this|that)\s+back\b", re.I),
    re.compile(r"\bpayback\s+period\b", re.I),
    re.compile(r"\breturn\s+on\s+investment\b", re.I),
    re.compile(r"\bROI\b"),
    re.compile(r"\bworth\s+(it|the\s+(cost|switch|extra|money|tuition))\b", re.I),
    re.compile(r"\bfinancially\s+worth\b", re.I),
    re.compile(r"\bmakes?\s+(financial\s+)?sense\b", re.I),
      # Subjective magnitude verdicts. The engine ranks nothing, so any
    # claim that one figure overwhelms another is the model's own
    # judgment dressed as a finding. Note "largest" is deliberately NOT
    # here -- "the largest difference in Fork's current comparison" is
    # approved Fork voice; these are the ones that editorialize.
    re.compile(r"\bdwarfs?\b", re.I),
    re.compile(r"\bdominat(es?|ing|ion)\b", re.I),
    re.compile(r"\bmost\s+consequential\b", re.I),
    re.compile(r"\bcarries?\s+the\s+most\s+weight\b", re.I),
    re.compile(r"\boverwhelm(s|ed|ing)?\b", re.I),
    re.compile(r"\bby\s+a\s+wide\s+margin\b", re.I),
    # Cross-domain importance claims -- Fork ranks nothing across unlike
    # dimensions (cost vs. timeline vs. career) unless the student stated
    # a priority, and even then the answer should describe ALIGNMENT with
    # that stated priority, never assert an objective ranking like these.
    re.compile(r"\bmatters?\s+more\s+than\b", re.I),
    re.compile(r"\btakes?\s+priority\s+over\b", re.I),
    re.compile(r"\boutweighs?\b", re.I),
    re.compile(r"\bmost\s+(important|significant)\s+(dimension|factor|consideration)\b", re.I),
    re.compile(r"\bmost\s+downstream\s+consequences?\b", re.I),
    re.compile(r"\b(single\s+)?(dimension|factor)\s+with\s+the\s+most\b", re.I),
    # A 1-year-after-graduation snapshot says nothing about whether the
    # gap persists. Claiming it recurs is an extrapolation the source
    # doesn't support.
    re.compile(r"\brecurs?\b", re.I),
    re.compile(r"\bevery\s+year\b", re.I),
    re.compile(r"\bannually\s+thereafter\b", re.I),
    # Unit reframing: the engine only ever states semester counts, never a
    # year-equivalent -- "almost a full academic year" is a conversion
    # Fork's engine never performed, the same category of invention as an
    # unsupported ratio, just in a different unit instead of a multiplier.
    re.compile(r"\b(almost|nearly|close to|about)\s+(an?\s+)?(full\s+)?(academic\s+)?year\b", re.I),
]

# A spelled-out multiplier ("five times more") can never be grounded,
# because number words never match the digit-based grounding regex in the
# first place — there's no allowlist entry to check it against, so it's
# rejected outright rather than compared to anything.
_RATIO_WORD_PATTERN = re.compile(
    r"\b(half|double|triple|quadruple|twice|one|two|three|four|five|six|"
    r"seven|eight|nine|ten)\s+(times\s+)?"
    r"(as\s+(much|many)|more|less|larger|smaller|higher|lower|greater|fewer)\b",
    re.I,
)

# A digit multiplier or percent comparison ("5x more", "3.2 times larger",
# "40% higher") MIGHT legitimately restate a real backend figure (e.g. a
# BLS growth percentage) — so these extract the number and check it
# against the same allowlist the main grounding pass uses, rather than
# banning the phrase outright. Only rejected when that specific number
# isn't itself something the calculation actually contains.
_RATIO_DIGIT_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:x|times)\s+"
    r"(?:as\s+(?:much|many)|more|less|larger|smaller|higher|lower|greater|fewer)\b",
    re.I,
)
_PERCENT_COMPARISON_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*%\s*(?:higher|lower|more|less|greater|smaller|fewer)\b",
    re.I,
)

# Payback/break-even claims often don't put the object word ("cost") right
# next to the verb — "the switching cost could be recovered in well under
# a year" has "recover" and the timeframe eleven words apart. A verb
# immediately followed by "cost" (the earlier _ALWAYS_BANNED_PATTERNS
# entry) is too narrow to catch that phrasing. These two patterns instead
# look for a payback-style verb and a duration phrase within the same
# sentence (a ~60-character window), in either order — catching both
# "recovered...in a year" and "in a year, you'd recover..." without
# needing a distinct pattern for every word order.
_PAYBACK_VERB = (
    r"recover(?:s|ed|ing)?"
    r"|pays?\s+(?:for\s+(?:itself|it|the\s+\w+)|off|back)"
    r"|earns?\s+back"
    r"|makes?\s+(?:it\s+)?back"
    r"|break[\s-]?even"
)
_SPELLED_NUMBER = (
    r"a|one|two|three|four|five|six|seven|eight|nine|ten|\d+"
)
_TIMEFRAME = rf"(?:within|in|under|less\s+than)\s+(?:{_SPELLED_NUMBER})?\s*(?:year|month|week)s?"

_PAYBACK_TIMEFRAME_PATTERN = re.compile(
    rf"\b(?:{_PAYBACK_VERB})\b[^.]{{0,60}}\b(?:{_TIMEFRAME})\b", re.I
)
_TIMEFRAME_PAYBACK_PATTERN = re.compile(
    rf"\b(?:{_TIMEFRAME})\b[^.]{{0,60}}\b(?:{_PAYBACK_VERB})\b", re.I
)


# --- alternative-count check --------------------------------------------
#
# A spelled-out count ("across all three alternatives") never matches the
# digit-based numeric-grounding regex, so a model that simply miscounts
# how many options are active passes grounding cleanly while stating
# something false. Observed in practice: a CAREER answer covering four
# active options ("Fork estimates..." once per option) opened with
# "the biggest difference across all three alternatives" while genuinely
# discussing four. This is a separate, explicit check for exactly that
# failure mode -- not a relationship the model invented, just a count it
# got wrong -- so the number of alternatives is a property CODE derives
# from the view's own option list, never left to the model's own tally.

_SPELLED_COUNT_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_ALTERNATIVE_COUNT_PATTERN = re.compile(
    r"\b(?:all\s+)?(one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(alternatives?|options?|majors?)\b",
    re.I,
)


def _counts_alternatives_correctly(text: str, active_option_count: int | None) -> bool:
    """True unless the text names a spelled-out alternative count that
    doesn't match how many options are actually active. `active_option_count`
    of None means "not applicable here" (e.g. the pairwise path, which is
    always exactly two majors and doesn't use this phrasing) -- always
    passes in that case."""
    if active_option_count is None:
        return True
    for match in _ALTERNATIVE_COUNT_PATTERN.finditer(text):
        if _SPELLED_COUNT_WORDS.get(match.group(1).lower()) != active_option_count:
            return False
    return True


def _has_invented_relationship(text: str, allowlist: set[str]) -> bool:
    """True if `text` contains a mathematical relationship (ratio,
    multiplier, payback/ROI/worth-it language) that isn't something the
    backend actually supplied. Deliberately broader than the exact
    phrasing seen in any one example — worded variants ("pays back",
    "break-even point", "5x the cost", "recoup the expense") are meant to
    be caught by the same patterns, not require a new one each time."""
    for pattern in _ALWAYS_BANNED_PATTERNS:
        if pattern.search(text):
            return True
    if _RATIO_WORD_PATTERN.search(text):
        return True
    if _PAYBACK_TIMEFRAME_PATTERN.search(text) or _TIMEFRAME_PAYBACK_PATTERN.search(text):
        return True
    for match in _RATIO_DIGIT_PATTERN.finditer(text):
        if not (_numeric_variants(float(match.group(1))) & allowlist):
            return True
    for match in _PERCENT_COMPARISON_PATTERN.finditer(text):
        if not (_numeric_variants(float(match.group(1))) & allowlist):
            return True
    return False


def _grounded_structured_explanation(
    system: str,
    user_message: str,
    formatted_result: dict,
    available_node_ids: list[str],
    fallback=None,
    active_option_count: int | None = None,
) -> dict:
    """
    Structured counterpart to _grounded_explanation (below, still used by
    explain_results/the /converse path): calls the model expecting the
    DecisionExplanation JSON schema, and on ANY failure -- invalid JSON,
    a schema mismatch, or a grounded-number check failing on the
    concatenation of every text field -- retries once with a stricter
    instruction, then falls back to a deterministic structured template
    if that also fails or the provider errors outright.

    `formatted_result` is whatever object the answer must be grounded
    against, and the allowlist is built from THAT object -- so passing a
    scoped view here (as the multi-option path does) is what gives topic
    scoping real enforcement rather than leaving it to the prompt. A
    career view contains no tuition figure, so a tuition figure in the
    answer has nothing to match against and fails.

    `active_option_count`, when given, is how many options are actually
    active -- checked against any spelled-out alternative count the model
    states in prose (see _counts_alternatives_correctly). Passed by the
    multi-option path only; pairwise answers never count alternatives.

    `fallback` builds the deterministic answer when the model can't
    produce a grounded one. Defaults to the pairwise template; the
    multi-option path passes its own, since a view has a different shape
    than a single formatted result.
    """
    if fallback is None:
        fallback = _fallback_explanation_structured

    allowlist = _build_number_allowlist(formatted_result)

    def _attempt(sys_prompt: str) -> tuple[DecisionExplanation | None, str]:
        """Returns (explanation, failure_reason). failure_reason is "" on
        success, and otherwise names which check failed so the retry can
        respond with a targeted correction instead of a one-size-fits-all
        message.

        The reasons are logged because "used_fallback: true" on its own is
        undiagnosable -- a provider timeout and the verifier catching an
        invented ratio look identical from outside, and they call for
        completely different fixes.
        """
        try:
            raw = _call_model(sys_prompt, user_message, max_tokens=900)
        except Exception as e:
            # NOT a grounding failure. Retrying with a stricter prompt
            # can't fix a provider outage, and mislabeling it hides the
            # real cause.
            logger.warning(
                "explanation attempt failed: provider error (%s): %s",
                type(e).__name__, e,
            )
            return None, "provider"
        explanation = _parse_structured_explanation(raw)
        if explanation is None:
            logger.warning("explanation attempt failed: response did not parse as valid JSON")
            return None, "parse"
        text = _explanation_text_for_grounding(explanation)
        if not _all_numbers_grounded(text, allowlist):
            logger.warning(
                "explanation attempt failed: ungrounded number (allowlist size %d)",
                len(allowlist),
            )
            return None, "grounding"
        # A second, separate check from number-grounding: two individually
        # real numbers can each be grounded while their RELATIONSHIP is
        # invented ("$39,839 is roughly five times larger than $8,498" —
        # both dollar figures are real, "five times larger" is not). The
        # numeric check alone can't catch this, and it can't catch it at
        # all when the multiplier is spelled out ("five") rather than
        # digits, since spelled-out numbers never match the numeric regex
        # in the first place.
        if _has_invented_relationship(text, allowlist):
            logger.warning("explanation attempt failed: invented relationship detected")
            return None, "relationship"
        if not _counts_alternatives_correctly(text, active_option_count):
            logger.warning(
                "explanation attempt failed: alternative count in prose didn't "
                "match the %s active option(s)",
                active_option_count,
            )
            return None, "grounding"
        explanation.related_node_ids = _filter_to_known_nodes(
            explanation.related_node_ids, available_node_ids
        )
        return explanation, ""

    first, failure = _attempt(system)
    if first is not None:
        return {"explanation": first, "used_fallback": False}

    retry_suffix = RELATIONSHIP_RETRY_SUFFIX if failure == "relationship" else STRUCTURED_RETRY_SUFFIX
    second, second_failure = _attempt(system + retry_suffix)
    if second is not None:
        return {"explanation": second, "used_fallback": False}

    logger.warning(
        "falling back to deterministic explanation (first=%s, second=%s)",
        failure, second_failure,
    )

    return {
        "explanation": fallback(formatted_result),
        "used_fallback": True,
    }


# Every structured-output prompt in this file explicitly says "no
# markdown fences" -- the live model doesn't always comply. Matches ONLY
# when the entire (already-stripped) response is one fence block, so it
# never reaches into surrounding prose to pull JSON out of it.
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _parse_model_json(raw: str) -> dict | list | None:
    """
    Parse one JSON object/array a model returned, tolerating exactly one
    presentation wrapper: the whole response fenced in ```json ... ``` or
    plain ``` ... ```. This is normalization of a known formatting
    habit, not a permissive JSON-repair system -- it does not scan for
    JSON embedded in prose, does not trim trailing commas or fix quoting,
    and does not attempt partial recovery of truncated output. Anything
    that still isn't valid JSON after stripping a whole-response fence
    returns None, the same as if this function didn't exist at all.

    Shared by classify_intent() and _parse_structured_explanation() (and,
    through it, both explain_decision() and explain_multi_comparison())
    so a live model's occasional fenced response doesn't have two
    separately-maintained tolerances that could drift apart.
    """
    text = raw.strip()
    match = _JSON_FENCE_RE.match(text)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _parse_structured_explanation(raw: str) -> DecisionExplanation | None:
    """Returns None rather than raising on anything that isn't valid JSON
    matching the schema -- invalid provider output is exactly the case
    meant to trigger a retry or fallback, not an exception."""
    data = _parse_model_json(raw)
    if data is None:
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

# =======================================================================
# Intent classification
# =======================================================================
#
# The one place natural-language UNDERSTANDING happens for Ask Fork.
# Shared by both /explain (Compare One) and /comparison/ask (Compare
# Multiple) -- this replaced three separate keyword tables (this file's
# old _QUESTION_FOCUS, conversation/router.py's _TOPIC_KEYWORDS,
# conversation/option_intent.py's marker tuples). What it returns is a
# small, closed, validated structure -- never prose, never a number, never
# a decision. Everything it returns is re-validated in code before it can
# touch session state; see conversation/router.py and
# conversation/option_intent.py for that validation layer.


class OptionMajorInput(BaseModel):
    """One major named in an add/replace instruction, with an optional
    transfer-credit figure IF the student stated one this same turn. None
    here means genuinely not stated -- never guessed, never carried over
    from a different major's figure (see conversation/orchestrator.py's
    Compare One replace handling).

    `reuse_credits_from` is the ONLY channel for "the same credits
    transfer over" -- the model names WHICH major's figure to reuse, and
    _validate_intent() resolves that into the actual number from trusted,
    code-computed known_option_credits. The model never writes that
    number into credits_transferable itself, even though the figure is
    visible to it in context: the trust boundary is that a copied number
    is still an AI-produced number, and code performing the lookup is
    what makes it a fact instead of a claim. Whichever value
    _validate_intent() resolves is the only one downstream code ever
    reads; reuse_credits_from is cleared once resolved."""

    major: str
    credits_transferable: int | None = None
    reuse_credits_from: str | None = None


class ConversationIntent(BaseModel):
    """
    Closed, validated natural-language intent for one Ask Fork turn.

    Every field is either a literal from a fixed enum or a list of major
    keys -- there is no free-text field the model can use to smuggle prose,
    a number, or an invented identifier through. Major keys are checked
    against the institution's real majors table by the caller (see
    conversation/option_intent.py's validation adapter) before anything
    here is trusted; this class only enforces shape, not real-world
    validity.
    """

    topic_scope: Literal[
        "broad", "financial", "timeline", "credits", "career", "unchanged", "unclear"
    ]
    option_change: Literal["none", "replace", "add", "remove", "restore", "unclear"] = "none"
    referenced_majors: list[str] = Field(default_factory=list)
    add_options: list[OptionMajorInput] = Field(default_factory=list)
    remove_options: list[str] = Field(default_factory=list)
    priority_update: Literal["financial", "timeline", "credits", "career", "cleared"] | None = None
    # Set only when pending_field_request context is non-null AND this
    # message states the number that answers it -- ordinary extraction
    # from the student's own words, the same trust category as any other
    # number they state directly (e.g. add_options' credits_transferable).
    # Never set otherwise, and never guessed from anything but this
    # message's own text.
    pending_field_value: int | None = None
    needs_clarification: bool = False
    clarification_type: Literal[
        "ambiguous_major",
        "ambiguous_option_change",
        "verdict_without_priority",
        "unclear_topic",
        "conflicting_priority",
    ] | None = None
    ambiguous_candidates: list[str] = Field(default_factory=list)


INTENT_SYSTEM_PROMPT = """You interpret one message from a student using \
Fork, a college-major comparison tool, and return ONLY a JSON object \
describing what they mean. You do not answer their question, you do not \
calculate anything, and you do not decide what is best for them -- \
another step does that using only the structured fields you return here.

You will be given the student's message plus trusted context: the \
conversation's current topic scope (or null on the first turn), which \
majors are currently active in the comparison, any priority the student \
has already explicitly stated (or null), which alternative's map is \
currently displayed (or null), any option-change instruction still \
awaiting resolution from a previous turn (or null), for majors Fork \
already has a transfer-credit figure for, what that figure is (so a \
student can say "same credits" without retyping it), and whether Fork is \
currently waiting on one specific missing number (or null).

Respond with ONLY a JSON object, no other text, no markdown fences, in \
exactly this shape:
{{
  "topic_scope": "broad" | "financial" | "timeline" | "credits" | "career" | "unchanged" | "unclear",
  "option_change": "none" | "replace" | "add" | "remove" | "restore" | "unclear",
  "referenced_majors": ["<major keys named in THIS message>"],
  "add_options": [{{"major": "<major key>", "credits_transferable": <integer or null>, "reuse_credits_from": "<major key to copy a KNOWN figure from, or null>"}}],
  "remove_options": ["<major keys to remove>"],
  "priority_update": "financial" | "timeline" | "credits" | "career" | "cleared" | null,
  "pending_field_value": <integer or null>,
  "needs_clarification": true | false,
  "clarification_type": "ambiguous_major" | "ambiguous_option_change" | "verdict_without_priority" | "unclear_topic" | "conflicting_priority" | null,
  "ambiguous_candidates": ["<candidate major keys, only when clarification_type is ambiguous_major>"]
}}

VALID MAJOR KEYS -- use exactly these, nothing else, ever:
{major_list}
If a name doesn't clearly resolve to exactly one key above (e.g. "psych" \
when both a B.A. and a B.S. exist), do NOT guess which one -- set \
needs_clarification=true, clarification_type="ambiguous_major", and list \
every plausible key in ambiguous_candidates. Never invent a key that \
isn't in the list above.

TOPIC SCOPE:
- "financial": cost, tuition, affordability, money, debt, budget.
- "timeline": graduation timing, how long, semesters remaining, delay.
- "credits": which credits transfer/apply, requirements, degree plan.
- "career": jobs, salary, earnings, occupations, job market, career outlook.
- "broad": an explicit request to see everything / all the tradeoffs / \
"compare them overall" / the single biggest difference across dimensions. \
This is NOT the same as asking who is "best" -- see verdict_without_priority.
- "unchanged": the message is a genuine follow-up with no topic words of \
its own ("why?", "what about the other two?", "and financially?" if \
"financially" IS a topic word -> use "financial" instead). Only use \
"unchanged" when nothing in the message signals a topic at all.
- "unclear": you cannot tell what the student is asking about, and it \
isn't a request for an unweighted verdict (that's verdict_without_priority \
instead). Pair with needs_clarification=true, clarification_type="unclear_topic".

OPTION CHANGES: only an EXPLICIT instruction to change who is being \
compared counts -- "add X", "drop X", "just compare X and Y", "put X \
back", "compare all again". A preference or interest statement ("I'm \
leaning toward IT", "CS looks nice", "tell me more about X") is NEVER an \
option_change -- it stays "none". If the instruction clearly means to \
narrow/add/remove but you can't tell which majors ("those two", "the \
other one") with no way to resolve it from context, set \
needs_clarification=true, clarification_type="ambiguous_option_change".

RESTORE: "put X back" / "restore X" names a specific major -- set \
option_change="restore" with add_options carrying just that major (no \
credits_transferable needed; code already knows its prior figure). \
"put them all back" / "compare all again" / "restore everything" names \
no one -- set option_change="restore" with add_options EMPTY, which \
means restore every previously-known alternative. The presence or \
absence of a named major is what distinguishes these two, exactly like \
the targeted-swap-vs-wholesale-narrow distinction above.

TWO DIFFERENT THINGS BOTH CALLED "replace" -- read the instruction \
carefully, because these produce different results downstream:
- TARGETED SWAP: "replace Psych BA with Psych BS, keep IT/Business/CS" \
names exactly which major(s) leave and which join; everyone else stays \
in the comparison. Set option_change="replace" with remove_options \
carrying the major(s) leaving AND add_options carrying the major(s) \
joining -- BOTH populated together is what signals a targeted swap.
- WHOLESALE NARROW: "just compare CS and IT" / "let's only look at CS \
and IT now" names the WHOLE new set with nothing said about keeping \
anyone else. Set option_change="replace" with add_options carrying the \
named majors and remove_options EMPTY -- that is what signals "narrow to \
exactly these," dropping everyone not named.
If the message explicitly says to KEEP certain majors while swapping \
another out, that is always a targeted swap, never a wholesale narrow --  \
do not drop majors the student just told you to keep.

CONTINUING A PENDING OPTION CHANGE: if pending_option_action in the \
context is not null, the student started an option-change instruction \
last turn that didn't fully resolve (e.g. they said "replace Psych BA" \
without naming what to replace it with, or a valid instruction failed to \
apply). If THIS message names a major, treat it as completing that \
SAME pending action -- reuse its action and already-known majors, and \
fill in what was missing from this message. Do not reinterpret a \
completing reply as a fresh "add" instruction. If this message still \
doesn't name anything usable (e.g. "can you replace it" with no major \
named), keep needs_clarification=true, clarification_type= \
"ambiguous_option_change", and keep option_change matching the pending \
action so the resulting question asks about the right thing.

REUSING A KNOWN CREDITS FIGURE: if the student explicitly says to reuse \
or carry over an already-known major's transfer-credit figure for a new \
major ("the same credits transfer over", "same as before", "use what I \
gave you for Psych BA"), set that new major's "reuse_credits_from" to the \
SOURCE major's key and leave "credits_transferable" null. Do NOT write \
the number yourself, even though known_option_credits shows it to you --  \
code looks up and assigns the actual figure; your job is only to \
identify WHICH major to copy from. Only use reuse_credits_from when the \
student explicitly asked for a figure to carry over, and only name a \
major that appears in known_option_credits; never assume two different \
majors share a transfer figure on your own. This is different from the \
student stating a NEW number directly in this message ("61 credits \
apply") -- that is ordinary extraction from their own words, so it still \
goes in credits_transferable exactly as before, with reuse_credits_from \
left null.

PRIORITY: only set priority_update when the student states, in this \
message, that something matters most/most importantly/is their biggest \
concern -- "cost matters most to me", "I care most about graduating \
quickly", "job opportunities are my biggest concern". A reaction or \
observation about one option ("CS looks nice", "that salary sounds good") \
is NEVER a priority statement -- leave priority_update null. Relative \
phrasing counts too: "I care more about graduating quickly than salary" \
is a priority statement for the thing that matters MORE (timeline here) \
-- set priority_update to that one dimension, the same as if the student \
had said "graduating quickly matters most." Do not try to represent the \
less-important side of the comparison; only the preferred dimension is \
stored. If the student states two different, competing priorities with \
no indication either matters more ("I care about both cost and speed"), \
do not pick one -- set needs_clarification=true, \
clarification_type="conflicting_priority", and leave priority_update \
null. Use priority_update="cleared" only when the student explicitly \
changes their mind or drops a previously stated priority.

VERDICT REQUESTS: "which one is best overall?" / "what should I do?" / \
"which is better?" -- with NO dimension named or implied -- asks Fork to \
declare a winner across dimensions Fork cannot weigh on its own. If the \
student has NOT stated a priority (context above is null), set \
needs_clarification=true, clarification_type="verdict_without_priority" \
and leave topic_scope as whatever it would otherwise be. If the student \
HAS already stated a priority, this is fine to resolve to that \
priority's topic_scope (e.g. timeline) with no clarification needed -- \
code will anchor the answer to their stated priority, not invent a \
universal ranking.

A SCOPED SUPERLATIVE IS NOT A VERDICT REQUEST -- this distinction \
matters and is easy to get wrong because both are phrased as "which one \
is X-est": "which gets me out fastest" (timeline), "which costs the \
least" (financial), "which keeps the most credits" (credits), "which \
has the highest reported salary" (career) each name ONE \
already-identifiable dimension. Resolve topic_scope to that one \
dimension and proceed normally -- no clarification needed, regardless of \
whether a priority has been stated. Only a request with NO dimension \
named or implied ("best overall", "which is better", "what should I \
do") is a genuine cross-dimension verdict request.

Do not confuse a verdict request with an explicit broad-comparison \
request: "compare all four overall" / "walk me through the tradeoffs" is \
topic_scope="broad", no clarification -- the student asked to see \
everything, not to be told who wins.

RESOLVING A PENDING FIELD REQUEST: if pending_field_request in the \
context is not null, Fork just asked the student for one specific \
missing number (e.g. how many credits apply to a given major). If this \
message states that number -- even inside a full sentence ("86 credits \
apply", "I think 86 apply", "about 86") -- set "pending_field_value" to \
that number: ordinary extraction from their own words, the same as \
reading any other number they state directly elsewhere. If this message \
does NOT answer that question -- it asks something else, changes the \
subject, or doesn't state a usable number -- leave pending_field_value \
null and classify the message normally instead (topic_scope, \
option_change, everything else as usual). Never guess a value; only set \
it when the message actually states one that answers the pending \
question."""

INTENT_RETRY_SUFFIX = """

Your previous answer wasn't valid JSON matching the required schema, or \
used a major key that isn't in the valid list. Respond again with ONLY \
the JSON object in the exact schema above, using only major keys from the \
valid list."""


def _validate_intent(
    intent: ConversationIntent,
    valid_majors: dict[str, str],
    known_option_credits: dict[str, int] | None = None,
) -> ConversationIntent:
    """
    Code-side validation of everything the classifier returned. This is
    the defensive pass -- the same pattern already used for
    related_node_ids (_filter_to_known_nodes) and extract_comparison_inputs's
    options list: nothing the model names is trusted until it's checked
    against the institution's real data.

    This is also where reuse_credits_from gets resolved into an actual
    number. The model is only ever trusted to say WHICH major's figure to
    reuse -- the lookup itself happens here, against known_option_credits
    (the same trusted, code-computed dict the model was shown), so a
    "same credits transfer over" instruction can never result in the
    model's own copy of that number reaching a calculation. Any
    credits_transferable the model wrote alongside a reuse_credits_from is
    discarded in favor of this lookup, not merged with it.
    """
    valid_keys = set(valid_majors)
    known_option_credits = known_option_credits or {}

    intent.referenced_majors = [m for m in intent.referenced_majors if m in valid_keys]
    intent.remove_options = [m for m in intent.remove_options if m in valid_keys]
    intent.add_options = [o for o in intent.add_options if o.major in valid_keys]
    intent.ambiguous_candidates = [m for m in intent.ambiguous_candidates if m in valid_keys]

    for option in intent.add_options:
        if option.reuse_credits_from is not None:
            option.credits_transferable = known_option_credits.get(option.reuse_credits_from)
            option.reuse_credits_from = None

    # A model-declared clarification always wins over any invariant below
    # -- it already decided it can't proceed confidently.
    if not intent.needs_clarification and intent.clarification_type is not None:
        intent.needs_clarification = True
    if intent.needs_clarification and intent.clarification_type is None:
        intent.clarification_type = "unclear_topic"

    # If validation stripped every major out of an add/remove/replace,
    # there's nothing left to act on -- never silently proceed with an
    # empty change, and never silently drop back to "none" either (that
    # would look like the instruction was ignored rather than misunderstood).
    if intent.option_change in ("add", "remove", "replace") and not (
        intent.add_options or intent.remove_options
    ):
        intent.needs_clarification = True
        intent.clarification_type = intent.clarification_type or "ambiguous_option_change"

    return intent


def classify_intent(
    message: str,
    valid_majors: dict[str, str],
    current_topic_scope: str | None,
    active_options: list[str],
    stated_priority: str | None,
    selected_detail_path: str | None,
    pending_option_action: dict | None = None,
    known_option_credits: dict[str, int] | None = None,
    pending_field_request: dict | None = None,
) -> ConversationIntent | None:
    """
    Interpret one student message into a closed, validated intent.

    `pending_option_action`, `known_option_credits`, and
    `pending_field_request` are the same kind of trusted context
    active_options/stated_priority already are -- validated, Fork-produced
    facts, never AI prose -- passed so a follow-up to an unresolved
    option-change instruction, an explicit "same credits as X", or a
    natural-language (not bare-number) reply to a pending missing field
    can be resolved without guessing. All optional, defaulting to no
    context (e.g. Compare One, which has no pending_option_action or
    known_option_credits concept).

    Returns None when the provider fails, or the response can't be parsed
    into a schema-valid ConversationIntent after one retry. Callers MUST
    treat None as "Ask Fork is temporarily unavailable" -- never as
    permission to guess a scope, fall back to keyword matching (there is
    none left), or mutate any state. This function performs no
    calculation and touches no session; it only classifies.
    """
    major_list = "\n".join(
        f"- {key}: {name}" for key, name in sorted(valid_majors.items())
    )
    system = INTENT_SYSTEM_PROMPT.format(major_list=major_list)
    user_message = json.dumps(
        {
            "message": message,
            "current_topic_scope": current_topic_scope,
            "active_options": active_options,
            "stated_priority": stated_priority,
            "selected_detail_path": selected_detail_path,
            "pending_option_action": pending_option_action,
            "known_option_credits": known_option_credits or {},
            "pending_field_request": pending_field_request,
        }
    )

    def _attempt(sys_prompt: str) -> ConversationIntent | None:
        try:
            raw = _call_model(sys_prompt, user_message, max_tokens=500, model=INTENT_MODEL)
        except Exception as e:
            logger.warning(
                "intent classification failed: provider error (%s): %s",
                type(e).__name__, e,
            )
            return None
        data = _parse_model_json(raw)
        if data is None:
            logger.warning("intent classification failed: response did not parse as JSON")
            return None
        try:
            return ConversationIntent.model_validate(data)
        except ValidationError:
            logger.warning("intent classification failed: response did not match schema")
            return None

    intent = _attempt(system)
    if intent is None:
        intent = _attempt(system + INTENT_RETRY_SUFFIX)
    if intent is None:
        return None

    return _validate_intent(intent, valid_majors, known_option_credits)


# =======================================================================
# Multi-option comparison
# =======================================================================
#
# Everything below serves the conversational, multi-option path. The
# pairwise functions above are untouched and still serve /explain and
# /converse.
#
# Two responsibilities, kept separate on purpose:
#   - extract_comparison_inputs() reads what the student SAID and turns it
#     into engine inputs. It never fills a gap; a value it wasn't given
#     comes back as missing.
#   - explain_multi_comparison() reads what the ENGINE PRODUCED and writes
#     it up. It never sees the student's raw message, only the authorized
#     view.


MULTI_EXTRACTION_SYSTEM_PROMPT = """You extract structured data from a \
student's message about comparing college majors. You do not calculate \
anything, you do not estimate anything, and you do not recommend anything. \
You only identify what the student has told you and map it to fields.

Valid major keys are exactly: {valid_keys}

A student is comparing their CURRENT major against one or more \
ALTERNATIVE majors. Transferable credits are per alternative — the same \
completed credits apply differently to different programs, so each \
alternative gets its own figure.

Respond with ONLY a JSON object, no other text, no markdown fences, in \
this exact shape:

{{
  "current_major": "<major key, or null if not stated>",
  "credits_completed": <integer, or null if not stated>,
  "options": [
    {{"major": "<major key>", "credits_transferable": <integer or null>}}
  ]
}}

Rules:
- If the student names a major that isn't in the valid key list, leave it \
out entirely rather than mapping it to the closest match.
- NEVER guess a transferable-credit figure. If the student named an \
alternative but didn't say how many credits transfer to it, set \
credits_transferable to null for that option. Null is a correct answer; an \
invented number is not.
- Do not assume all credits transfer, and do not assume none do.
- Include every alternative the student named, even the ones missing a \
transfer figure.
- If the student's current major appears in their list of alternatives, \
still report it as current_major and you may leave it out of options."""


def extract_comparison_inputs(message: str, valid_major_keys: list[str]) -> dict:
    """
    Read a free-text setup message into multi-option comparison inputs.

    Returns {"parsed": dict, "missing": list[str]} where `parsed` is the
    raw structure and `missing` names any REQUIRED top-level field the
    student didn't supply. Per-option missing transfer figures are not
    listed here -- those are legitimately incomplete options, handled as
    pending further down rather than as a failure to understand.

    Valid major keys come from the institution's own data rather than a
    hardcoded list, so adding a major to the data doesn't mean editing a
    prompt.
    """
    system = MULTI_EXTRACTION_SYSTEM_PROMPT.format(
        valid_keys=", ".join(valid_major_keys)
    )
    raw = _call_model(system, message)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"AI extraction did not return valid JSON: {raw!r}") from e

    options = parsed.get("options") or []
    # Drop anything the model produced that isn't a real major key. The
    # prompt already forbids it; this is the check that doesn't depend on
    # the model listening.
    options = [
        o for o in options
        if isinstance(o, dict) and o.get("major") in valid_major_keys
    ]
    parsed["options"] = options

    missing = []
    if parsed.get("current_major") not in valid_major_keys:
        missing.append("current_major")
    if parsed.get("credits_completed") is None:
        missing.append("credits_completed")
    if not [o for o in options if o["major"] != parsed.get("current_major")]:
        missing.append("options")

    return {"parsed": parsed, "missing": missing}


MULTI_COMPARISON_SYSTEM_PROMPT = """You are Fork, a decision translator for \
a college student comparing their current major against one or more \
alternatives. You will be given a JSON object containing an ALREADY-\
CALCULATED comparison, scoped to the topic the student is currently asking \
about, plus their question.

You may ONLY reference numbers and facts present in that JSON object. \
Never calculate, estimate, or round anything differently than shown. Never \
introduce a fact, source, number, or citation that isn't in the object. If \
a number you want isn't in the object, it is not available to you — say so \
or describe the finding in words.

EVERY option in the object is being compared. Do not quietly drop one \
because it seems less relevant. If an option's status is "pending", it is \
missing an input Fork needs — say which field is missing and that Fork \
needs it, and never state or imply a figure for that option. If an \
option's status is "failed", explain briefly that it couldn't be \
calculated and why.

WHAT YOU MUST NOT DO — this is the core of Fork's design:
- Never rank unlike dimensions against each other. Tuition, semesters, \
credit applicability, and earnings are different kinds of consequence. \
Never say one matters more than another, never assign weights, never \
produce an overall score, and never name an overall "best" or "winner".
- Never recommend a major or tell the student what to choose.
- Never create a NEW mathematical relationship between two values the \
backend didn't already compute: no ratios or multipliers ("three times \
more"), no percent comparisons you worked out yourself, no payback \
periods, break-even points, ROI, or "worth it" judgments, no per-month \
figure derived from an annual one.
- If you refer to how many alternatives are in this comparison, count \
only the options that actually appear in the object below -- do not \
state a number from memory or estimate it.

WHAT YOU MAY DO:
- Compare like with like. "Option A's estimated additional tuition is \
higher than Option B's" is a comparison of the same measurement and is \
fine. So are semesters against semesters, credits against credits, and one \
reported earnings figure against another.
- Restate a relationship the object already contains.
- Say plainly when options don't meaningfully differ on something. "These \
three are within a semester of each other" is a real and useful finding, \
not a failure to find something.

If the student has stated a priority of their own (for example, that \
graduating quickly matters most to them), you may explain which options \
align with THAT stated priority — because they supplied it. Do not invent \
a priority they never expressed, and do not turn their priority into an \
overall recommendation.

{scope_instruction}

Valid node ids you may use in related_node_ids (nothing else): {node_id_list}.
Pick roughly 1-3 that the answer genuinely discusses, not everything
technically connected -- an earnings answer might link salary and career
nodes; a graduation-delay answer might link credit transfer and
time-to-graduate. Leave it empty if nothing specific applies.

Rules that matter as much as the numbers:
- If a figure's status is "privacy_suppressed" or "unavailable", say it's \
missing and why — never state or imply a number for it, and never call a \
missing comparison "no change" (that phrase means a real measured zero, \
not absent data).
- A measured zero difference IS a real finding. Some majors share one \
federal earnings category, so "no measured difference in reported \
earnings" is correct information, not missing data. Say it that way.
- College Scorecard earnings describe graduates who received federal aid \
and were working and not enrolled when measured — not every graduate, and \
not a prediction for this student. Say "graduates in this data".
- Occupations linked to a major come from the federal CIP-SOC crosswalk: \
occupations commonly related to that field, by expert judgment. NOT a \
record of where graduates actually went. Never say a major "leads to" a job.
- Credit figures the student typed are not an official audit. Never say \
credits are "wasted", "lost", or "count toward nothing" — say what Fork \
currently estimates based on what they entered, and that a what-if audit \
would confirm it.

RESPOND WITH ONLY a JSON object (no markdown fences, no other text) in \
exactly this shape:
{{
  "direct_answer": "1-3 sentences answering the question directly. Start \
with the actual finding, not 'There are several things to consider'.",
  "key_points": [{{"title": "short title", "explanation": "plain-English \
explanation referencing actual numbers and majors from the object"}}],
  "limitations": [{{"title": "short limitation", "explanation": "what the \
data cannot prove and why"}}],
  "still_useful_for": ["one short phrase per thing this comparison IS \
still useful for"],
  "next_step": {{"action": "one concrete action", "reason": "why it would \
improve the decision"}},
  "related_node_ids": ["zero or more ids from the list above that this \
answer specifically discusses"]
}}

next_step should be JSON null, not omitted, when no practical next step \
applies.

You may neutrally mention other things the student could look at ("you can \
dig into cost, graduation time, credits, or career outcomes"). You may not \
tell them which one to look at next or which one should matter to them.

Keep the whole response to roughly 120-250 words unless the question asks \
for a full breakdown."""


def explain_multi_comparison(
    view: dict, question: str, available_nodes: list[dict] | None = None
) -> dict:
    """
    Explain an authorized view of a multi-option comparison.

    `view` is both the payload the model sees AND the object its numbers
    are verified against -- that identity is the point. See
    conversation/views.py. The focus instruction comes from
    `_topic_focus_instruction()`, the same shared table Compare One uses --
    both callers are driven by the same intent classification, just with
    different consequences (Compare Multiple gates data via build_view();
    Compare One only gates emphasis).

    `available_nodes` enables related-node navigation in Compare Multiple,
    which previously always returned an empty related_node_ids regardless
    of what the model wrote -- the prompt told it to leave the list empty,
    and even if it hadn't, the ids would have been filtered against an
    empty allowlist. Same {"id", "label"} shape and same
    _filter_to_known_nodes() defense as explain_decision().

    Returns {"explanation": DecisionExplanation, "used_fallback": bool,
    "topic_scope": str}.
    """
    scope = view.get("topic_scope", "broad")
    available_nodes = available_nodes or []
    available_ids = [n["id"] for n in available_nodes if "id" in n]
    node_id_list = ", ".join(available_ids) if available_ids else "(none provided)"

    system = MULTI_COMPARISON_SYSTEM_PROMPT.format(
        scope_instruction=_topic_focus_instruction(scope),
        node_id_list=node_id_list,
    )
    user_message = json.dumps({"comparison": view, "question": question})

    result = _grounded_structured_explanation(
        system,
        user_message,
        view,
        available_node_ids=available_ids,
        fallback=_fallback_multi_explanation,
        active_option_count=len(view.get("options", [])),
    )
    return {
        "explanation": result["explanation"],
        "used_fallback": result["used_fallback"],
        "topic_scope": scope,
    }


def _top_occupation_title(career_context: list[dict] | None, major_display: str) -> str | None:
    """The top (most-common-nationally) occupation title for one major out
    of a career_context list, or None if there's nothing to show. Purely
    for the deterministic fallback -- picks the first entry rather than
    ranking, since career_context is already sorted that way upstream."""
    if not career_context:
        return None
    for entry in career_context:
        if entry.get("major") == major_display:
            occupations = entry.get("occupations") or []
            if occupations:
                return occupations[0].get("title")
    return None


def _fallback_multi_explanation(view: dict) -> DecisionExplanation:
    """
    Deterministic multi-option answer, built entirely from string
    formatting against the view. No model call, so there is nothing here
    that could be invented. Used when the model can't produce a grounded
    answer twice running, or the provider fails outright.

    Deliberately plain. The priority is that every sentence is true, not
    that it's insightful -- and it still refuses to rank the options
    against each other, because the fallback has to obey the same rules
    the model does.
    """
    anchor = view.get("current_major", "your current major")
    options = view.get("options", [])
    calculated = [o for o in options if o.get("status") == "calculated"]
    pending = [o for o in options if o.get("status") == "pending"]
    failed = [o for o in options if o.get("status") == "failed"]

    names = ", ".join(o["major"] for o in options) or "no options"
    direct = (
        f"Here's what Fork calculated for {anchor} compared against {names}, "
        "based on the credits you entered."
    )

    key_points: list[KeyPoint] = []
    for option in calculated:
        data = option.get("data", {})
        bits: list[str] = []

        financial = data.get("financial", {})
        cost = financial.get("incremental_total_cost", {}).get("value")
        if cost is not None:
            direction = "more" if cost > 0 else "less" if cost < 0 else "about the same"
            bits.append(
                f"a total difference of {_money(abs(cost))} {direction}"
                if cost != 0
                else "about the same total"
            )

        timeline = data.get("timeline", {})
        semesters = timeline.get("incremental_semesters", {}).get("value")
        if semesters is not None:
            if semesters > 0:
                bits.append(f"{semesters} more semester(s)")
            elif semesters < 0:
                bits.append(f"{abs(semesters)} fewer semester(s)")
            else:
                bits.append("no change to graduation timing")

        # Salary figures live under "earnings" (split out from "career" so
        # FINANCIAL can be authorized for them without also authorizing
        # Job Market Demand/occupation data -- see views.py's _SCOPE_BLOCKS).
        earnings = data.get("earnings", {})
        delta = earnings.get("annual_salary_delta", {}).get("value")
        if delta is not None and delta != 0:
            direction = "higher" if delta > 0 else "lower"
            bits.append(
                f"reported early-career earnings {_money(abs(delta))}/yr {direction}"
            )
        elif delta == 0:
            bits.append("no measured difference in reported early-career earnings")

        # Occupation/job-market data, when the view carries it (CAREER
        # scope only). Without this, a CAREER answer that falls back to
        # this deterministic template would silently drop to
        # earnings-only -- the exact regression this fix closes.
        career_block = data.get("career", {})
        top_occupation = _top_occupation_title(career_block.get("career_context"), option["major"])
        if top_occupation:
            bits.append(f"occupation data available including {top_occupation}")

        if bits:
            key_points.append(
                KeyPoint(
                    title=option["major"],
                    explanation="Fork estimates " + "; ".join(bits) + ".",
                )
            )

    limitations: list[Limitation] = []
    for option in pending:
        fields = ", ".join(option.get("missing_fields", [])) or "a required input"
        limitations.append(
            Limitation(
                title=f"{option['major']} isn't calculated yet",
                explanation=(
                    f"Fork still needs {fields} for {option['major']}. It hasn't "
                    "been estimated, so there are no figures for it here."
                ),
            )
        )
    for option in failed:
        limitations.append(
            Limitation(
                title=f"{option['major']} couldn't be calculated",
                explanation=option.get("error", "Its inputs didn't validate."),
            )
        )

    if not calculated:
        direct = (
            f"Fork doesn't have enough information yet to compare anything "
            f"against {anchor}."
        )

    return DecisionExplanation(
        direct_answer=direct,
        key_points=key_points,
        limitations=limitations,
        still_useful_for=[
            "Comparing estimated tuition, timing, and credit impact side by side",
        ],
        next_step=None,
        related_node_ids=[],
    )