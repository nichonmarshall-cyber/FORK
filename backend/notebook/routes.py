"""
/notebook: the signed-in student's academic record.

Every route resolves the student from their session cookie and only ever
queries rows with that student's id. Ids belonging to another student are
reported as not found -- the same response as an id that doesn't exist -- so
nothing can be learned by guessing.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from accounts.auth import current_student, require_csrf_header, require_writable
from data_loading.loader import UnknownInstitution, build_reference_data
from db.config import get_db
from db.models import Student

from . import dashboard
from . import documents as D
from . import facts as F
from . import scenarios as S
from . import timeline
from .storage import StorageUnavailable, get_storage

router = APIRouter(prefix="/notebook", tags=["notebook"])
mutating = [Depends(require_csrf_header), Depends(require_writable)]


def _reference(student: Student) -> dict:
    try:
        return build_reference_data(student.institution_id)
    except UnknownInstitution as e:
        raise HTTPException(status_code=404, detail=str(e))


def _error(status: int, message: str, code: str = "notebook_error", **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"status": code, "message": message, **extra})


@router.get("")
def get_notebook(student: Student = Depends(current_student), db: Session = Depends(get_db)):
    return dashboard.build_dashboard(db, student, _reference(student))


# --- profile facts ------------------------------------------------------


class ProfileBody(BaseModel):
    """Student-reported facts. Only fields present in the request change;
    an explicit null clears that field."""

    current_major: str | None = None
    gpa: float | None = Field(default=None, ge=0, le=4.0)
    credits_completed: int | None = Field(default=None, ge=0, le=300)
    credits_in_progress: int | None = Field(default=None, ge=0, le=30)
    catalog_year: str | None = Field(default=None, max_length=32)

    @field_validator("gpa")
    @classmethod
    def _two_places(cls, v):
        return None if v is None else round(v, 2)


_FIELD_WORDS = {
    "current_major": "current major",
    "gpa": "GPA",
    "credits_completed": "completed credits",
    "credits_in_progress": "credits in progress",
    "catalog_year": "catalog year",
}


@router.put("/profile", dependencies=mutating)
def update_profile(
    body: ProfileBody,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
):
    edits = body.model_dump(exclude_unset=True)
    reference = _reference(student)
    majors = reference["majors"]

    if edits.get("current_major") is not None:
        from decision_paths.change_major.major_resolution import (
            AmbiguousMajorError,
            UnsupportedMajorError,
            resolve_major,
        )

        try:
            edits["current_major"] = resolve_major("current_major", edits["current_major"]).key
        except (AmbiguousMajorError, UnsupportedMajorError) as e:
            raise _error(422, str(e), "validation_error")
        if edits["current_major"] not in majors:
            raise _error(422, "Fork doesn't have data for that major yet.", "validation_error")

    try:
        changes = F.apply_student_edits(db, student.id, edits)
    except F.FactConflict as e:
        db.rollback()
        raise _error(409, str(e), "document_backed", field=e.key)

    if changes:
        parts = []
        for key, _old, new in changes:
            words = _FIELD_WORDS[key]
            if new is None:
                parts.append(f"cleared your {words}")
            elif key == "current_major":
                parts.append(f"set your {words} to {majors.get(new, {}).get('display_name', new)}")
            else:
                parts.append(f"set your {words} to {new}")
        text = "You " + "; ".join(parts) + " (your own figures)."
        timeline.record_event(
            db,
            student.id,
            timeline.FACTS_UPDATED,
            text[0].upper() + text[1:],
            detail={"changed": [{"key": k, "old": o, "new": n} for k, o, n in changes]},
        )
    db.commit()
    return dashboard.build_dashboard(db, student, reference)


# --- documents ----------------------------------------------------------


class FromAuditBody(BaseModel):
    audit_session_id: str
    document: str = "current"


@router.post("/documents/from-audit", dependencies=mutating)
def save_from_audit(
    body: FromAuditBody,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
):
    from session.store import SessionNotFound, academic_sessions

    try:
        audit_session = academic_sessions.get(body.audit_session_id)
    except SessionNotFound:
        raise _error(
            404,
            "That audit review has expired. Upload the audit again and confirm it, "
            "then add it to your record.",
            "session_not_found",
        )

    reference = _reference(student)
    try:
        document, created = D.save_audit_from_session(
            db, student.id, audit_session, body.document, reference["majors"]
        )
    except D.DocumentError as e:
        db.rollback()
        raise _error(e.status_code, str(e))
    db.commit()
    facts = F.get_facts(db, student.id)
    return {"created": created, "document": D.serialize_document(document, facts)}


class RecordDocumentBody(BaseModel):
    doc_type: str
    title: str = Field(max_length=200)
    document_date: str | None = None
    note: str | None = Field(default=None, max_length=2000)


@router.post("/documents", status_code=201, dependencies=mutating)
def record_document(
    body: RecordDocumentBody,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
):
    try:
        document = D.record_document(
            db,
            student.id,
            doc_type=body.doc_type,
            title=body.title,
            document_date=body.document_date,
            note=body.note,
        )
    except D.DocumentError as e:
        db.rollback()
        raise _error(e.status_code, str(e), "validation_error")
    db.commit()
    return {"document": D.serialize_document(document, [])}


@router.post("/documents/{document_id}/file", dependencies=mutating)
async def attach_document_file(
    document_id: str,
    file: UploadFile = File(...),
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
):
    try:
        document = D.get_owned_document(db, student.id, document_id)
        if document.source != D.STUDENT_RECORDED:
            raise D.DocumentError(
                "Fork keeps what it read from audits, not the audit file itself.", 400
            )
        data = await file.read(D.MAX_FILE_BYTES + 1)
        D.attach_file(
            db, student.id, document, data, file.content_type or "", file.filename
        )
    except D.DocumentError as e:
        db.rollback()
        raise _error(e.status_code, str(e))
    db.commit()
    return {"document": D.serialize_document(document, F.get_facts(db, student.id))}


@router.get("/documents/{document_id}/file")
def download_document_file(
    document_id: str,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
):
    try:
        document = D.get_owned_document(db, student.id, document_id)
    except D.DocumentError as e:
        raise _error(e.status_code, str(e))
    if document.storage_status != "stored" or not document.storage_key:
        raise _error(404, "Fork doesn't have a file stored for this document.")
    try:
        storage = get_storage()
        if storage is None:
            raise StorageUnavailable("Document storage is turned off.")
        data = storage.read(document.storage_key)
    except (StorageUnavailable, FileNotFoundError):
        raise _error(404, "That file isn't available from storage any more.")
    filename = (document.original_filename or "document").replace('"', "")
    return Response(
        content=data,
        media_type=document.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/documents/{document_id}", dependencies=mutating)
def delete_document(
    document_id: str,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
):
    try:
        document = D.get_owned_document(db, student.id, document_id)
        D.remove_document(db, student.id, document)
    except D.DocumentError as e:
        db.rollback()
        raise _error(e.status_code, str(e))
    db.commit()
    return dashboard.build_dashboard(db, student, _reference(student))


# --- saved comparisons --------------------------------------------------


class ScenarioOptionBody(BaseModel):
    major: str
    credits_transferable: int | None = Field(default=None, ge=0, le=300)
    credits_transferable_source: str = "Student-reported"


class SaveScenarioBody(BaseModel):
    current_major: str
    credits_completed: int = Field(ge=0, le=300)
    credits_in_progress: int = Field(default=0, ge=0, le=30)
    credits_source: str = "Student-reported"
    options: list[ScenarioOptionBody] = Field(min_length=1, max_length=4)
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    #: The audit review session the compare page is using, if any. Lets a
    #: comparison built from an audit confirmed this visit -- but not yet
    #: added to the record -- keep its document provenance.
    audit_session_id: str | None = None


def _resolve_key(field: str, key: str) -> str:
    from decision_paths.change_major.major_resolution import (
        AmbiguousMajorError,
        UnsupportedMajorError,
        resolve_major,
    )

    try:
        return resolve_major(field, key).key
    except AmbiguousMajorError as e:
        raise _error(422, str(e), "clarification_required", options=e.options)
    except UnsupportedMajorError as e:
        raise _error(422, e.explanation, "unsupported_program")


def _audit_session_or_none(audit_session_id: str | None, student_id: str):
    if not audit_session_id:
        return None
    from session.store import SessionNotFound, academic_sessions

    try:
        session = academic_sessions.get(audit_session_id)
    except SessionNotFound:
        return None
    owner = D._claimed_audit_sessions.get(audit_session_id)
    if owner is not None and owner != student_id:
        return None
    return session


@router.post("/scenarios", status_code=201, dependencies=mutating)
def save_scenario(
    body: SaveScenarioBody,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
):
    reference = _reference(student)
    majors = reference["majors"]
    current_key = _resolve_key("current_major", body.current_major)
    options = []
    for option in body.options:
        data = option.model_dump()
        data["major"] = _resolve_key("options", option.major)
        options.append(data)

    audit_session = _audit_session_or_none(body.audit_session_id, student.id)
    inputs = S.build_inputs(
        db,
        student.id,
        current_major=current_key,
        credits_completed=body.credits_completed,
        credits_in_progress=body.credits_in_progress,
        credits_source=body.credits_source,
        options=options,
        audit_session=audit_session,
        majors=majors,
    )
    try:
        outcome = S.calculate(inputs, reference)
    except S.ScenarioError as e:
        raise _error(e.status_code, str(e), "validation_error")
    if all(o["status"] == "failed" for o in outcome["options"]):
        # Nothing in it calculated or is waiting on a figure: there's no
        # comparison to keep, only an error to fix.
        raise _error(
            422,
            outcome["options"][0].get("error") or "None of these options could be calculated.",
            "validation_error",
        )
    scenario = S.save(db, student.id, inputs, outcome, body.title, body.note)
    db.commit()
    return {"scenario": S.serialize(scenario)}


class UpdateScenarioBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    decision: str | None = None


@router.patch("/scenarios/{scenario_id}", dependencies=mutating)
def update_scenario(
    scenario_id: str,
    body: UpdateScenarioBody,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
):
    fields = body.model_dump(exclude_unset=True)
    try:
        scenario = S.get_owned(db, student.id, scenario_id)
        if "title" in fields and fields["title"] and fields["title"].strip():
            scenario.title = fields["title"].strip()[:200]
        if "note" in fields:
            scenario.note = (fields["note"] or "").strip()[:2000] or None
        if "decision" in fields:
            S.set_decision(db, student.id, scenario, fields["decision"])
    except S.ScenarioError as e:
        db.rollback()
        raise _error(e.status_code, str(e))
    db.commit()
    return {"scenario": S.serialize(scenario)}


@router.post("/scenarios/{scenario_id}/refresh", dependencies=mutating)
def refresh_scenario(
    scenario_id: str,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
):
    try:
        scenario = S.get_owned(db, student.id, scenario_id)
        changed = S.refresh(db, student.id, scenario, _reference(student))
    except S.ScenarioError as e:
        db.rollback()
        raise _error(e.status_code, str(e))
    db.commit()
    return {"changed": changed, "scenario": S.serialize(scenario)}


@router.delete("/scenarios/{scenario_id}", dependencies=mutating)
def delete_scenario(
    scenario_id: str,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
):
    try:
        scenario = S.get_owned(db, student.id, scenario_id)
        S.remove(db, student.id, scenario)
    except S.ScenarioError as e:
        db.rollback()
        raise _error(e.status_code, str(e))
    db.commit()
    return {"status": "deleted"}


# --- timeline -----------------------------------------------------------


@router.get("/timeline")
def get_timeline(
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = None,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
):
    events = timeline.list_events(db, student.id, limit=limit, before=before)
    return {"events": [dashboard.serialize_event(e) for e in events]}
