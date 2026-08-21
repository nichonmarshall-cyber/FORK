"""
Fork API entrypoint.

Run with: uvicorn main:app --reload
Swagger docs appear automatically at http://localhost:8000/docs — FastAPI
generates them from the models below, no extra work needed.
"""
import os
import uuid

from dotenv import load_dotenv
load_dotenv()  # load .env so the API key is set before anything below
               # tries to use it


from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError, field_validator

from data_loading.loader import UnknownInstitution, build_reference_data
from decision_paths.change_major import engine as change_major_engine
from decision_paths.change_major.formatter import format_result
from decision_paths.change_major.inputs import ChangeMajorInputs, MissingInputs
from decision_paths.change_major.major_resolution import (
    AmbiguousMajorError,
    UnsupportedMajorError,
    resolve_major,
)
from decision_paths.change_major.comparison_inputs import (
    ComparisonOption,
    MultiComparisonInputs,
)
from decision_paths.change_major.metadata import CHANGE_MAJOR_METADATA
from conversation.orchestrator import (
    compute_pairwise_navigation,
    handle_pairwise_turn,
    handle_turn,
    start_comparison,
)
from conversation.session import SESSIONS
from audit_import.parser import parse_audit_pdf, propose_engine_inputs

app = FastAPI(
    title="Fork API",
    description="Academic and financial decision support for college students. "
                "The AI never does the math — every number here traces back to a "
                "deterministic engine and a data source you can go check.",
    version="0.1.0",
)

# Browsers enforce this, so it decides which sites may call the API using a
# visitor's credentials. A wildcard on a public deployment lets any page on
# the internet drive this backend from someone else's browser -- and every
# request here costs an Anthropic call, so the bill and the rate limit are
# both ours.
#
# Origins come from the environment rather than the source so the deployed
# frontend's URL isn't baked into a public repository, and so this file
# doesn't need editing to add one. Comma-separated; defaults to local
# development, which is what running with no configuration should mean.
_DEFAULT_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"

_allowed_origins = [
    origin.strip()
    for origin in os.environ.get("FORK_ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Until the request carries an institution_id (Stage 2), everything runs
# against the one supported school.
_DEFAULT_INSTITUTION_ID = "unt"


def _load_reference_data(institution_id: str = _DEFAULT_INSTITUTION_ID) -> dict:
    # The loader re-reads files per request on purpose — same behavior the
    # old single-file read had: small files, and a number can be corrected
    # mid-demo without restarting the server.
    return build_reference_data(institution_id)


@app.exception_handler(RequestValidationError)
async def _shape_request_validation_errors(request: Request, exc: RequestValidationError):
    """Give FastAPI's own request-body rejections Fork's error shape.

    Field constraints on a request model are enforced before the route body
    runs -- which is what we want, since it means invalid input never reaches
    an LLM call. But FastAPI's default body is a raw list of pydantic error
    dicts, while everything else in Fork returns {status, message, errors}.
    Without this the caller parses two formats depending on which layer
    caught the problem, and the frontend's parseApiError understands one.
    """
    errors = [
        {
            "field": ".".join(str(p) for p in e.get("loc", ()) if p != "body"),
            "message": e.get("msg", "Invalid input."),
        }
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "status": "validation_error",
                "message": errors[0]["message"] if errors else "Invalid input.",
                "errors": errors,
            }
        },
    )


def _clean_validation_errors(exc: ValidationError) -> list[dict]:
    """
    Turns Pydantic's ValidationError into a small, honest list of
    {field, message} entries — no docs URLs, no `[type=value_error,
    input_value=..., input_type=dict]` internals, no Python repr.

    For a custom @field_validator that raises ValueError (our case here),
    Pydantic wraps the original exception in err["ctx"]["error"] and adds
    a "Value error, " prefix to err["msg"]. The original exception's own
    str() is already the clean message the validator author wrote, so
    that's what this prefers. Falls back to stripping the known boilerplate
    prefix for error types that don't carry ctx.error (e.g. Pydantic's own
    built-in type/range validators), so nothing here depends on every
    error being hand-raised.
    """
    cleaned = []
    for err in exc.errors():
        original = err.get("ctx", {}).get("error")
        message = str(original) if original is not None else err["msg"]
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        field = ".".join(str(p) for p in err["loc"]) if err["loc"] else None
        cleaned.append({"field": field, "message": message})
    return cleaned


def _resolve_major_or_raise(field: str, key: str) -> tuple[str, str | None]:
    """
    Runs a caller-supplied major key through resolve_major() and converts
    its two special-case exceptions into the HTTP responses a client can
    actually act on:
      - ambiguous (e.g. "psychology") -> 422 with the real options listed
      - unsupported (e.g. "nursing")  -> 422 with why, so a frontend can
        show a clear "not offered this way" message instead of a generic
        validation error
    Returns (resolved_key, warning_or_None) on success.
    """
    try:
        resolved = resolve_major(field, key)
    except AmbiguousMajorError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "clarification_required",
                "field": e.field,
                "message": str(e),
                "options": e.options,
            },
        )
    except UnsupportedMajorError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "unsupported_program",
                "field": e.field,
                "key": e.key,
                "message": e.explanation,
            },
        )
    return resolved.key, resolved.warning


@app.get("/decision-paths")
def list_decision_paths():
    """The frontend calls this to discover which decision paths exist. It
    doesn't need to know how any of them calculate."""
    return [CHANGE_MAJOR_METADATA.__dict__]


class ChangeMajorRequest(BaseModel):
    current_major: str
    prospective_major: str
    credits_completed: int
    credits_transferable: int
    # Provenance plus anything from an uploaded audit. The defaults keep
    # the manual-entry path working exactly as it did before.
    credits_source: str = "Student-reported"
    credits_transferable_source: str = "Student-reported"
    credits_source_date: str = "Not stated"
    credits_in_progress: int = 0
    prospective_credits_required: int | None = None
    prospective_credits_required_source: str | None = None
    # Which school's data to calculate against. Defaults to the one
    # currently-supported institution so every existing caller — the
    # manual-entry form, direct API tests — keeps working unchanged.
    institution_id: str = _DEFAULT_INSTITUTION_ID


def _run_change_major_calculation(request: ChangeMajorRequest) -> dict:
    """
    Structured request in, formatted result out. Shared by the calculate
    endpoint and the explain endpoint, so both ground their output in a
    number the backend actually computed — not one a client claimed. A
    client-supplied "here's the calculation, now explain it" payload would
    let the grounding check faithfully verify a number that was never
    real; recomputing here closes that off entirely.
    """
    payload = request.model_dump()
    institution_id = payload.pop("institution_id")

    warnings: list[str] = []
    for field in ("current_major", "prospective_major"):
        resolved_key, warning = _resolve_major_or_raise(field, payload[field])
        payload[field] = resolved_key
        if warning:
            warnings.append(warning)

    try:
        inputs = ChangeMajorInputs(**payload)
    except ValidationError as e:
        errors = _clean_validation_errors(e)
        raise HTTPException(
            status_code=422,
            detail={
                "status": "validation_error",
                "message": errors[0]["message"] if errors else "Invalid input.",
                "errors": errors,
            },
        )

    try:
        reference_data = _load_reference_data(institution_id)
    except UnknownInstitution as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        result = change_major_engine.calculate(inputs, reference_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    formatted = format_result(result)
    if warnings:
        formatted["warnings"] = warnings
    return formatted


@app.post("/decision-paths/change-major/calculate")
def calculate_change_major(request: ChangeMajorRequest):
    """
    Structured values in, projection out. No AI anywhere in this path.

    Used by the manual-entry form, by direct testing, and as the fallback
    if the AI layer has trouble during a demo. The conversation endpoint
    also lands here once it has valid inputs.
    """
    return _run_change_major_calculation(request)


class AvailableNode(BaseModel):
    """One entry from the frontend's own node list — id plus its display
    label. Sent with every /explain request so the backend can (a) tell
    the model which node ids genuinely exist, and (b) filter the model's
    related_node_ids response against that same list. The map's node ids
    are defined once, in the frontend; this avoids a second, driftable
    copy of that list in Python."""

    id: str
    label: str


class ExplainRequest(BaseModel):
    """
    Same shape as ChangeMajorRequest plus the question and which node is
    currently open. Carries the calculation INPUTS, not a client-supplied
    result — see _run_change_major_calculation's docstring for why this
    endpoint recomputes rather than trusting a snapshot.
    """

    current_major: str
    prospective_major: str

    # Constraints mirror ChangeMajorInputs deliberately. This endpoint
    # recomputes the calculation, so the same inputs must be rejected here
    # for the same reasons -- but the enforcement has to happen at the
    # REQUEST boundary, not later when ChangeMajorRequest is constructed.
    #
    # Without these, an out-of-range figure is accepted by FastAPI, reaches
    # handle_pairwise_turn, and spends an intent-classification provider
    # call before anything checks it. If that call fails the student is told
    # "Ask Fork is temporarily unavailable" when the actual problem is their
    # own input, and if it succeeds Fork has paid for a round trip on a
    # request that was always going to 422.
    credits_completed: int = Field(..., ge=0, le=300)
    credits_transferable: int = Field(..., ge=0)
    credits_source: str = "Student-reported"
    credits_transferable_source: str = "Student-reported"
    credits_source_date: str = "Not stated"
    credits_in_progress: int = Field(default=0, ge=0, le=30)
    prospective_credits_required: int | None = Field(default=None, ge=1, le=300)
    prospective_credits_required_source: str | None = None
    institution_id: str = _DEFAULT_INSTITUTION_ID

    @field_validator("credits_transferable")
    @classmethod
    def transferable_cannot_exceed_completed(cls, v, info):
        """Same cross-field rule ChangeMajorInputs enforces.

        Copied rather than shared because the two models are validated at
        different layers; if this rule ever changes, both need updating and
        a test covers each.
        """
        completed = info.data.get("credits_completed")
        if completed is not None and v > completed:
            raise ValueError(
                "credits_transferable cannot exceed credits_completed "
                f"(got {v} transferable vs {completed} completed)."
            )
        return v

    question: str
    selected_node_id: str | None = None
    selected_node_label: str | None = None
    selected_node_question: str | None = None
    available_nodes: list[AvailableNode] = []
    # Optional continuity for Compare One's chat -- lets Ask Fork resolve
    # "unchanged" topic scope and remember a stated priority across turns.
    # Omitted (or unrecognized/expired) simply starts a fresh session;
    # /explain still recomputes the projection itself either way, never
    # trusting anything stored against it. See conversation/session.py.
    session_id: str | None = None


@app.post("/decision-paths/change-major/explain")
def explain_change_major(request: ExplainRequest):
    """
    Answers a follow-up question about a Change Major calculation with a
    structured explanation (direct answer, prioritized key points and
    limitations, what the comparison is still useful for, an optional
    next step, and which map nodes it touches on) -- or, for an
    option-change instruction ("compare me to X instead"), resolves that
    instruction instead of answering a question this turn. See
    conversation.orchestrator.handle_pairwise_turn for the full flow and
    conversation.orchestrator.PairwiseTurnIntent for the branches below.

    Recomputes the calculation from the same inputs the frontend already
    has (rather than accepting a pre-built result), so the AI is grounded
    against a number this backend just verified, not one the client
    claimed. If the intent-classification provider call fails, this
    returns "ai_unavailable" without ever computing or explaining
    anything for that turn -- see the module docstring in
    ai/interface.py's classify_intent(). If explanation generation fails
    after a successfully resolved intent, explain_decision() already
    falls back to a deterministic, always-true structured summary rather
    than raising, so there's no separate handling needed for that case.
    """
    from ai.interface import explain_decision

    try:
        reference_data = _load_reference_data(request.institution_id)
    except UnknownInstitution as e:
        raise HTTPException(status_code=404, detail=str(e))
    valid_majors = {
        key: entry["display_name"] for key, entry in reference_data["majors"].items()
    }

    session = SESSIONS.get_or_create(request.session_id, request.institution_id)
    turn = handle_pairwise_turn(
        session,
        request.question,
        request.current_major,
        request.prospective_major,
        request.credits_completed,
        valid_majors,
    )

    if turn.ai_unavailable:
        return {
            "status": "ai_unavailable",
            "message": (
                "Ask Fork is temporarily unavailable. Your calculated "
                "comparison has not been affected. Please try again in a "
                "moment."
            ),
            "state": {"session_id": session.session_id},
        }
    if turn.needs_clarification:
        return {
            "status": "clarification_required",
            "message": turn.clarification,
            "state": {"session_id": session.session_id},
        }
    if turn.applied_option_change is not None:
        return {
            "status": "option_change_applied",
            "applied_option_change": turn.applied_option_change,
            "state": {"session_id": session.session_id},
        }
    if turn.short_circuit_explanation is not None:
        return {
            "status": "complete",
            "state": {"session_id": session.session_id},
            **turn.short_circuit_explanation,
            "related_node_ids": [],
            "navigation_pills": [],
            "navigation_target": None,
            "topic_scope": None,
            "used_fallback": False,
        }

    calc_request = ChangeMajorRequest(
        current_major=request.current_major,
        prospective_major=request.prospective_major,
        credits_completed=request.credits_completed,
        credits_transferable=request.credits_transferable,
        credits_source=request.credits_source,
        credits_transferable_source=request.credits_transferable_source,
        credits_source_date=request.credits_source_date,
        credits_in_progress=request.credits_in_progress,
        prospective_credits_required=request.prospective_credits_required,
        prospective_credits_required_source=request.prospective_credits_required_source,
        institution_id=request.institution_id,
    )
    formatted = _run_change_major_calculation(calc_request)

    result = explain_decision(
        formatted,
        question=request.question,
        node_id=request.selected_node_id,
        node_label=request.selected_node_label,
        node_question=request.selected_node_question,
        available_nodes=[n.model_dump() for n in request.available_nodes],
        topic_scope=turn.topic_scope or "broad",
    )
    explanation = result["explanation"]
    pills, target = compute_pairwise_navigation(explanation.related_node_ids)
    return {
        "status": "complete",
        "state": {"session_id": session.session_id},
        "direct_answer": explanation.direct_answer,
        "key_points": [kp.model_dump() for kp in explanation.key_points],
        "limitations": [lim.model_dump() for lim in explanation.limitations],
        "still_useful_for": explanation.still_useful_for,
        "next_step": explanation.next_step.model_dump() if explanation.next_step else None,
        "related_node_ids": explanation.related_node_ids,
        "navigation_pills": pills,
        "navigation_target": target,
        "topic_scope": result["topic_scope"],
        "used_fallback": result["used_fallback"],
    }


class ConversationRequest(BaseModel):
    message: str
    institution_id: str = _DEFAULT_INSTITUTION_ID


@app.post("/decision-paths/change-major/converse")
def converse_change_major(request: ConversationRequest):
    """
    Free-text entrypoint. The AI extracts the inputs, the engine does the
    math, the AI writes the explanation. Requires ANTHROPIC_API_KEY.
    """
    # Imported here rather than at module level so the rest of the API
    # runs, and its tests pass, on a machine with no API key configured.
    from ai.interface import extract_inputs, explain_results

    try:
        inputs = extract_inputs(request.message)
    except MissingInputs as e:
        return {
            "status": "needs_more_information",
            "missing_fields": e.missing_fields,
        }

    warnings: list[str] = []
    for field, key in (
        ("current_major", inputs.current_major),
        ("prospective_major", inputs.prospective_major),
    ):
        resolved_key, warning = _resolve_major_or_raise(field, key)
        if resolved_key != key:
            inputs = inputs.model_copy(update={field: resolved_key})
        if warning:
            warnings.append(warning)

    try:
        reference_data = _load_reference_data(request.institution_id)
    except UnknownInstitution as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        result = change_major_engine.calculate(inputs, reference_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    formatted = format_result(result)
    if warnings:
        formatted["warnings"] = warnings
    formatted["explanation"] = explain_results(formatted)
    formatted["status"] = "complete"
    return formatted


# =======================================================================
# Multi-option conversational comparison
# =======================================================================
#
# Entirely additive. /calculate, /explain and /converse above are
# unchanged and keep working exactly as they did -- the manual form path
# and the demo fallback don't depend on any of this.
#
# Session state lives in memory, in this process. Restarting the server
# clears every conversation. That's a deliberate limitation for this
# version; see conversation/session.py for the reasoning.


class ComparisonOptionRequest(BaseModel):
    """One alternative major. credits_transferable may be omitted -- that
    marks the option pending rather than failing the whole comparison."""

    major: str
    credits_transferable: int | None = None
    credits_transferable_source: str = "Student-reported"
    prospective_credits_required: int | None = None
    prospective_credits_required_source: str | None = None


class StartComparisonRequest(BaseModel):
    current_major: str
    credits_completed: int
    options: list[ComparisonOptionRequest]
    credits_source: str = "Student-reported"
    credits_source_date: str = "Not stated"
    credits_in_progress: int = 0
    institution_id: str = _DEFAULT_INSTITUTION_ID
    session_id: str | None = None


def _build_multi_inputs(request: StartComparisonRequest) -> MultiComparisonInputs:
    """Resolve every major key, then validate. Resolution happens first so
    an ambiguous or unsupported major produces the same clear 422 the
    pairwise endpoints already return."""
    current_key, _ = _resolve_major_or_raise("current_major", request.current_major)

    options = []
    for option in request.options:
        key, _ = _resolve_major_or_raise("options", option.major)
        options.append(
            ComparisonOption(
                major=key,
                credits_transferable=option.credits_transferable,
                credits_transferable_source=option.credits_transferable_source,
                prospective_credits_required=option.prospective_credits_required,
                prospective_credits_required_source=option.prospective_credits_required_source,
            )
        )

    try:
        return MultiComparisonInputs(
            current_major=current_key,
            credits_completed=request.credits_completed,
            options=options,
            credits_source=request.credits_source,
            credits_source_date=request.credits_source_date,
            credits_in_progress=request.credits_in_progress,
        )
    except ValidationError as e:
        errors = _clean_validation_errors(e)
        raise HTTPException(
            status_code=422,
            detail={
                "status": "validation_error",
                "message": errors[0]["message"] if errors else "Invalid comparison inputs.",
                "errors": errors,
            },
        )


@app.post("/decision-paths/change-major/comparison/start")
def start_multi_comparison(request: StartComparisonRequest):
    """
    Set up (or replace) a multi-option comparison and run it.

    One request, N deterministic pairwise calculations. The student never
    runs the form once per major.
    """
    inputs = _build_multi_inputs(request)

    try:
        reference_data = _load_reference_data(request.institution_id)
    except UnknownInstitution as e:
        raise HTTPException(status_code=404, detail=str(e))

    session = SESSIONS.get_or_create(request.session_id, request.institution_id)
    session.institution_id = request.institution_id

    try:
        snapshot = start_comparison(session, inputs, reference_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "status": "ready",
        "state": session.to_state_dict(),
        "comparison": snapshot.to_dict(),
    }


class ConversationTurnRequest(BaseModel):
    session_id: str
    message: str
    # Per-request hint, never persisted server-side -- which alternative's
    # map the frontend currently has open. Used only to resolve "this
    # one" and to decide whether an auto-focus should also switch paths;
    # never affects active_options. See conversation/orchestrator.py's
    # _compute_navigation.
    selected_detail_path: str | None = None
    available_nodes: list[AvailableNode] = []


@app.post("/decision-paths/change-major/comparison/ask")
def ask_multi_comparison(request: ConversationTurnRequest):
    """
    One conversational turn against an established comparison.

    The response carries the conversation state back so a client can show
    what's currently being compared. Active options, topic scope, and
    stated priority are independent -- a topic question never narrows the
    option set, and neither ever overwrites the other.
    """
    session = SESSIONS.get(request.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={
                "status": "session_not_found",
                "message": "That conversation isn't available any more. Sessions "
                           "are held in memory and are cleared when the server "
                           "restarts. Start a new comparison to continue.",
            },
        )
    if session.inputs is None:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "no_comparison",
                "message": "Set up a comparison before asking about it.",
            },
        )

    try:
        reference_data = _load_reference_data(session.institution_id)
    except UnknownInstitution as e:
        raise HTTPException(status_code=404, detail=str(e))

    result = handle_turn(
        session,
        request.message,
        reference_data,
        selected_detail_path=request.selected_detail_path,
        available_nodes=[n.model_dump() for n in request.available_nodes],
    )

    if result.ai_unavailable:
        return {
            "status": "ai_unavailable",
            "message": (
                "Ask Fork is temporarily unavailable. Your calculated "
                "comparison has not been affected. Please try again in a "
                "moment."
            ),
            "state": session.to_state_dict(),
        }

    if result.needs_clarification:
        return {
            "status": "clarification_required",
            "message": result.clarification,
            "state": session.to_state_dict(),
        }

    return {
        "status": "complete",
        "state": session.to_state_dict(),
        "answer": result.explanation,
        "used_fallback": result.used_fallback,
        "navigation_pills": result.navigation_pills,
        "navigation_target": result.navigation_target,
        "topic_scope": session.current_topic_scope,
        # Always included on "complete" now that a chat instruction can
        # change the option set mid-conversation -- echoing only `state`
        # (as before) would silently omit a brand-new option's own entry,
        # which never existed in any snapshot the client already has.
        "comparison": session.snapshot.to_dict() if session.snapshot else None,
    }


class ExtractComparisonRequest(BaseModel):
    message: str
    institution_id: str = _DEFAULT_INSTITUTION_ID


@app.post("/decision-paths/change-major/comparison/extract")
def extract_multi_comparison(request: ExtractComparisonRequest):
    """
    Read a free-text setup message into comparison inputs.

    Deliberately does NOT calculate. It returns what the AI understood
    plus what's still missing, so the values can be confirmed before
    anything is priced. A transfer figure the student didn't give comes
    back null -- never estimated.
    """
    from ai.interface import extract_comparison_inputs

    try:
        reference_data = _load_reference_data(request.institution_id)
    except UnknownInstitution as e:
        raise HTTPException(status_code=404, detail=str(e))

    valid_keys = list(reference_data["majors"].keys())
    extracted = extract_comparison_inputs(request.message, valid_keys)
    parsed = extracted["parsed"]

    pending = [
        o["major"] for o in parsed.get("options", [])
        if o.get("credits_transferable") is None
    ]

    return {
        "status": "needs_more_information" if extracted["missing"] else "parsed",
        "proposal": parsed,
        "missing_fields": extracted["missing"],
        "options_missing_transfer_credits": pending,
        "requires_confirmation": True,
    }


MAX_AUDIT_BYTES = 5 * 1024 * 1024  # 5 MB; real audits are a few hundred KB


@app.post("/audit/parse")
async def parse_degree_audit(file: UploadFile = File(...)):
    """
    Read a degree audit PDF and propose input values.

    Deliberately calculates nothing and returns no projection. It returns
    suggestions plus the basis for each one, which go into editable fields
    for the student to confirm. If the parser misreads "58 HOURS" as 5.8, a
    person should catch that before the engine prices it.

    The file is held in memory, parsed, and discarded. An audit contains a
    student ID and a full grade history, and this application has no
    authentication, no encryption at rest, and no retention policy, so it
    must not be saved anywhere.
    """
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=415,
            detail=f"Expected a PDF, got '{file.content_type}'.",
        )

    contents = await file.read()

    if len(contents) > MAX_AUDIT_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 5 MB limit.")
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file was empty.")

    try:
        audit = parse_audit_pdf(contents)
    except Exception as e:
        # Don't leak a traceback to the client. A malformed PDF is a
        # user-facing problem, not a server error.
        raise HTTPException(
            status_code=422,
            detail=f"Couldn't read this PDF as a degree audit: {type(e).__name__}",
        )
    finally:
        # Explicit: nothing holds onto the bytes past this request.
        del contents

    return {
        "status": "parsed" if audit.parsed_anything else "unrecognized",
        "proposal": propose_engine_inputs(audit),
        "requires_confirmation": True,
    }

# ---------------------------------------------------------------------------
# UNT degree audit: upload, review, correct, confirm.
#
# Separate from /audit/parse above, which stays as the school-agnostic path for
# documents this parser doesn't recognise. These routes produce a normalized
# academic record held in a server-side session, and none of them calculate
# anything — the matcher isn't built, and wiring incomplete totals into the
# Change Major engine would put a number on screen that nothing stands behind.
# ---------------------------------------------------------------------------


class AcknowledgeBody(BaseModel):
    evidence_fingerprint: str
    institution_id: str = _DEFAULT_INSTITUTION_ID


class CorrectionBatchBody(BaseModel):
    corrections: list["CorrectionBody"]


class CorrectionBody(BaseModel):
    field: str
    value: str | float | None = None
    course_key: str | None = None


def _session_or_404(session_id: str):
    from session.store import SessionNotFound, academic_sessions

    try:
        return academic_sessions.get(session_id)
    except SessionNotFound:
        raise HTTPException(
            status_code=404,
            detail="That session has expired or doesn't exist. Uploading the "
                   "document again will start a new one.",
        )


def _session_payload(session, institution_id: str = _DEFAULT_INSTITUTION_ID) -> dict:
    from audit_import.unt.review import build_review
    # active_mode and uploaded_source are deliberately separate. A parsed
    # record awaiting review exists while manual is still active, and a client
    # that derives one from the other cannot see that state.
    payload = {
        "session_id": session.session_id,
        "active_mode": session.mode.value,
        "uploaded_source": session.uploaded_source.model_dump(mode="json"),
        "active_source_label": session.active_source_description,
    }
    if session.uploaded_record is not None:
        payload["review"] = build_review(session.uploaded_record).model_dump()

    # Only once confirmed. Before that the record is something Fork read but
    # the student hasn't checked, and offering engine inputs from it would
    # invite a caller to skip the review step entirely.
    from adapters.confirmed_record_to_inputs import build_inputs_from_confirmed_record

    engine_inputs = build_inputs_from_confirmed_record(session)
    if engine_inputs is not None:
        payload["change_major_inputs"] = engine_inputs.model_dump(mode="json")

    # Document classification and resolution. The logic lives in
    # documents.resolution as pure functions; this only serialises what they
    # return. Nothing here decides anything -- see that module's docstring.
    payload["documents"] = _resolve_documents(session, institution_id)

    return payload


def _resolve_documents(session, institution_id: str) -> dict:
    """What the confirmed collection establishes, ready for the form.

    Returns values for the frontend to APPLY to the form -- it does not, and
    must not, assign comparison inputs. The audit session and the
    conversation session are separate stores with no link between them; the
    student applies these figures, presses Calculate, and that calculation is
    what Ask Fork grounds on. See the Stage 2 notes in
    documents/resolution.py.
    """
    from documents.resolution import classify_document, resolve_comparison_inputs

    try:
        majors = _load_reference_data(institution_id)["majors"]
    except UnknownInstitution:
        majors = {}

    current = session.uploaded_record if session.has_confirmed_record else None
    stored = session.what_if_document
    what_if = stored.record if stored and stored.is_confirmed else None

    what_if_classification = (
        classify_document(what_if, majors) if what_if is not None else None
    )
    pending_classification = (
        classify_document(stored.record, majors)
        if stored is not None and what_if is None
        else None
    )

    resolved = resolve_comparison_inputs(
        current,
        what_if,
        what_if_classification,
        session.manual_transferable_by_major,
        acknowledged=session.is_acknowledged(majors),
    )

    # Named rather than repeating the `or` in both the condition and the
    # body: evaluating it twice reads as though the two could differ, and
    # leaves the value Optional at the point it's dereferenced.
    classification = what_if_classification or pending_classification

    return {
        "current_audit": {
            "present": session.uploaded_record is not None,
            "confirmed": session.has_confirmed_record,
        },
        "what_if": {
            "present": stored is not None,
            "confirmed": bool(stored and stored.is_confirmed),
            "classification": (
                classification.model_dump(mode="json") if classification else None
            ),
        },
        # Typed, unimplemented, and said so plainly rather than accepting a
        # file and doing nothing with it.
        "transcript": {
            "present": False,
            "supported": False,
            "message": (
                "Fork can't read transcripts yet. Degree audits are the "
                "supported document for now."
            ),
        },
        "resolved": resolved.model_dump(mode="json"),
        "evidence_fingerprint": session.current_evidence_fingerprint(majors),
    }


@app.post("/audit/unt/upload")
async def upload_unt_audit(
    file: UploadFile = File(...),
    session_id: str | None = None,
    institution_id: str = _DEFAULT_INSTITUTION_ID,
):
    """Parse a UNT degree audit and open a session holding the result.

    The record starts unconfirmed and the session starts in manual mode. A
    document Fork has read but the student hasn't checked is not yet something
    to calculate from.

    The file is parsed in memory and discarded. An audit carries a student ID
    and a full grade history, and this application has no authentication and no
    retention policy, so it doesn't get saved.
    """
    from audit_import.unt.parser import UnsupportedDocument, parse_audit_pdf
    from session.store import academic_sessions

    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=415,
            detail="Fork can read UNT degree audits saved as PDF. This file "
                   "doesn't look like a PDF.",
        )

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="That file was empty.")
    if len(contents) > MAX_AUDIT_BYTES:
        raise HTTPException(
            status_code=413, detail="That file is larger than the 5 MB limit."
        )

    try:
        record = parse_audit_pdf(contents)
    except UnsupportedDocument as e:
        # A real technical failure: the document couldn't be processed. Distinct
        # from a document that parsed fine but left Fork unable to confirm
        # something, which is not an error and never arrives here.
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        del contents

    # The parser already tells us which kind this is, from UNT's own
    # not-finalized banner. Routing on that rather than asking the student
    # to categorise their own upload.
    from session.context import StoredDocument

    if record.is_what_if:
        session = (
            academic_sessions.get(session_id)
            if session_id
            else academic_sessions.create()
        )
        session.attach_what_if(
            StoredDocument(document_id=uuid.uuid4().hex, record=record)
        )
    else:
        session = academic_sessions.create()
        session.attach_record(record)

    return _session_payload(session, institution_id)


@app.get("/audit/session/{session_id}")
def get_academic_session(session_id: str):
    return _session_payload(_session_or_404(session_id))


@app.post("/audit/session/{session_id}/correct")
def correct_academic_record(session_id: str, correction: CorrectionBody):
    """Apply a student's edit to the extracted record.

    Any edit returns the record to awaiting-review: confirmation covers a
    specific set of values, so changing one afterwards would leave the session
    claiming agreement to something never shown.
    """
    from session.context import CorrectionRequest

    session = _session_or_404(session_id)
    outcome = session.apply_correction(CorrectionRequest(**correction.model_dump()))

    if not outcome.applied:
        raise HTTPException(status_code=400, detail=outcome.message or "Couldn't apply that change.")

    return {"correction": outcome.model_dump(), **_session_payload(session)}


@app.post("/audit/session/{session_id}/corrections")
def correct_academic_record_batch(session_id: str, body: CorrectionBatchBody):
    """Apply everything the student changed in the review dialog at once.

    Batched rather than one request per field because the totals check runs
    after the whole set. Applying them one at a time would reconcile against
    intermediate states that never existed on screen and could report a
    mismatch that resolves itself two fields later.

    A single invalid field doesn't reject the batch. The valid corrections
    apply, the outcomes say which one failed and why, and the record is never
    left in a state the student didn't ask for.
    """
    from session.context import CorrectionRequest

    session = _session_or_404(session_id)
    outcomes = session.apply_corrections(
        [CorrectionRequest(**c.model_dump()) for c in body.corrections]
    )

    return {
        "corrections": [o.model_dump() for o in outcomes],
        "applied_count": sum(1 for o in outcomes if o.applied),
        "rejected": [o.model_dump() for o in outcomes if not o.applied],
        **_session_payload(session),
    }


@app.post("/audit/session/{session_id}/confirm")
def confirm_academic_record(
    session_id: str,
    document: str = "current",
    institution_id: str = _DEFAULT_INSTITUTION_ID,
):
    """Accept the extracted record as the session's academic source.

    Confirmation means the student agrees Fork read their document correctly.
    It is not verification: nothing here has been checked with UNT, and no
    response may describe it that way.
    """
    session = _session_or_404(session_id)

    from academic_record.enums import ConfirmationStatus

    if document == "what_if":
        stored = session.what_if_document
        if stored is None:
            raise HTTPException(
                status_code=400, detail="There is no What-If audit to confirm."
            )
        stored.confirmation_status = ConfirmationStatus.CONFIRMED
        for course in stored.record.courses:
            course.provenance.confirmed_by_student = True
        # Confirming a document is not acknowledging a disagreement between
        # documents. Any previous acknowledgement is dropped so the student
        # sees the comparison as it now stands.
        session.acknowledged_evidence = None
        session.touch()
    else:
        try:
            session.confirm()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return _session_payload(session, institution_id)


@app.post("/audit/session/{session_id}/acknowledge")
def acknowledge_document_discrepancies(session_id: str, body: AcknowledgeBody):
    """Accept that two confirmed documents disagree, and proceed anyway.

    A different question from /confirm, which asks whether Fork read ONE
    document correctly. This asks whether the student accepts how several
    confirmed documents sit together. Neither substitutes for the other:
    discrepancies can't even be computed until both documents are confirmed,
    so confirming the second one must not silently acknowledge a conflict
    nobody has seen.

    The client sends back the fingerprint it displayed. If the documents have
    changed since -- a correction, a replacement, a revert -- the fingerprint
    won't match and the acknowledgement is refused rather than granted. That
    is the difference between consent and a leftover flag.
    """
    session = _session_or_404(session_id)

    try:
        majors = _load_reference_data(body.institution_id)["majors"]
    except UnknownInstitution as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not session.acknowledge(body.evidence_fingerprint, majors):
        raise HTTPException(
            status_code=409,
            detail={
                "status": "evidence_changed",
                "message": (
                    "Your documents changed since you last looked at them. "
                    "Please review the differences again before continuing."
                ),
            },
        )

    return _session_payload(session, body.institution_id)


@app.post("/audit/session/{session_id}/mode")
def set_academic_mode(session_id: str, mode: str):
    """Switch between manual entry and the confirmed uploaded record.

    Switching to manual clears the uploaded record, so the two can never supply
    competing values for the same figure.
    """
    from academic_record.enums import AcademicInputMode

    session = _session_or_404(session_id)

    if mode == AcademicInputMode.MANUAL.value:
        session.switch_to_manual()
    elif mode == AcademicInputMode.CONFIRMED_UPLOAD.value:
        if not session.has_confirmed_record:
            raise HTTPException(
                status_code=400,
                detail="Review and confirm the uploaded record before using it.",
            )
        session.mode = AcademicInputMode.CONFIRMED_UPLOAD
        session.touch()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown mode '{mode}'.")

    return _session_payload(session)

@app.get("/health")
def health():
    return {"status": "ok"}