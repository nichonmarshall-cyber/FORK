"""
Fork — API entrypoint.

Run with: uvicorn main:app --reload
Swagger UI then appears automatically at http://localhost:8000/docs
(FastAPI generates this from the Pydantic models below — no extra work.)
"""

import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.decision_paths.change_major.tests import engine as change_major_engine
from decision_paths.change_major.formatter import format_result
from decision_paths.change_major.inputs import ChangeMajorInputs, MissingInputs
from decision_paths.change_major.metadata import CHANGE_MAJOR_METADATA

app = FastAPI(
    title="Fork API",
    description="Evidence-based academic and financial decision support for college students. "
                "The AI layer never calculates — every number in every response traces back "
                "to a deterministic engine and a cited data source.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before any real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data_sources", "change_major_reference.json")


def _load_reference_data() -> dict:
    # Reloaded per-request deliberately for now: cheap, and means editing
    # the JSON file during a demo doesn't require a server restart.
    # Cache this once the file is large enough that I/O is a bottleneck.
    with open(_DATA_PATH) as f:
        return json.load(f)


@app.get("/decision-paths")
def list_decision_paths():
    """Registry endpoint: the frontend calls this to know what's available,
    without knowing anything about how each path calculates its results."""
    return [CHANGE_MAJOR_METADATA.__dict__]


class ChangeMajorRequest(BaseModel):
    current_major: str
    prospective_major: str
    credits_completed: int
    credits_transferable: int


@app.post("/decision-paths/change-major/calculate")
def calculate_change_major(request: ChangeMajorRequest):
    """
    Structured endpoint: bypasses the AI layer entirely, for direct
    testing, the demo backup path, and the frontend's manual-entry mode.
    This is also the endpoint the AI-conversation flow calls internally
    once it has extracted valid inputs.
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
    Conversational entrypoint: AI extracts inputs from free text, engine
    calculates, AI explains. Requires ANTHROPIC_API_KEY to be set.
    """
    # Imported lazily so the rest of the API works, and its tests run,
    # even in environments without an API key configured.
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


@app.get("/health")
def health():
    return {"status": "ok"}