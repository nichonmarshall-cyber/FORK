"""
Fork API entrypoint.

Run with: uvicorn main:app --reload
Swagger docs appear automatically at http://localhost:8000/docs — FastAPI
generates them from the models below, no extra work needed.
"""

from dotenv import load_dotenv
load_dotenv()  # load .env so the API key is set before anything below
               # tries to use it

import json
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from decision_paths.change_major import engine as change_major_engine
from decision_paths.change_major.formatter import format_result
from decision_paths.change_major.inputs import ChangeMajorInputs, MissingInputs
from decision_paths.change_major.metadata import CHANGE_MAJOR_METADATA
from audit_import.parser import parse_audit_pdf, propose_engine_inputs

app = FastAPI(
    title="Fork API",
    description="Academic and financial decision support for college students. "
                "The AI never does the math — every number here traces back to a "
                "deterministic engine and a data source you can go check.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # FIXME restrict this before deploying anywhere public
    allow_methods=["*"],
    allow_headers=["*"],
)

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data_sources", "change_major_reference.json")


def _load_reference_data() -> dict:
    # Re-read per request on purpose. The file is small, and it means a
    # number can be corrected mid-demo without restarting the server. Worth
    # caching once the file gets large enough for the I/O to matter.
     with open(_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


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


@app.post("/decision-paths/change-major/calculate")
def calculate_change_major(request: ChangeMajorRequest):
    """
    Structured values in, projection out. No AI anywhere in this path.

    Used by the manual-entry form, by direct testing, and as the fallback
    if the AI layer has trouble during a demo. The conversation endpoint
    also lands here once it has valid inputs.
    """
    try:
        inputs = ChangeMajorInputs(**request.model_dump())
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    reference_data = _load_reference_data()

    try:
        result = change_major_engine.calculate(inputs, reference_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return format_result(result)


class ConversationRequest(BaseModel):
    message: str


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

    reference_data = _load_reference_data()
    result = change_major_engine.calculate(inputs, reference_data)
    formatted = format_result(result)
    formatted["explanation"] = explain_results(formatted)
    formatted["status"] = "complete"
    return formatted


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


def _session_payload(session) -> dict:
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
    return payload


@app.post("/audit/unt/upload")
async def upload_unt_audit(file: UploadFile = File(...)):
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

    session = academic_sessions.create()
    session.attach_record(record)
    return _session_payload(session)


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


@app.post("/audit/session/{session_id}/confirm")
def confirm_academic_record(session_id: str):
    """Accept the extracted record as the session's academic source.

    Confirmation means the student agrees Fork read their document correctly.
    It is not verification: nothing here has been checked with UNT, and no
    response may describe it that way.
    """
    session = _session_or_404(session_id)

    try:
        session.confirm()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _session_payload(session)


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
