"""
/account: register, sign in, sign out, who am I, delete my account.

Deleting an account removes the student row and, by ON DELETE CASCADE, every
document record, fact, saved comparison, timeline event, and sign-in session
that belongs to it -- plus any original files held in document storage. That
is the whole retention policy: Fork keeps a record until its owner deletes it.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.config import get_db
from db.models import AcademicDocument, Student
from notebook import timeline
from notebook.storage import StorageUnavailable, get_storage

from . import rate_limit
from .auth import (
    clear_cookie,
    client_address,
    current_student,
    end_session,
    require_csrf_header,
    start_session,
)
from .passwords import burn_equivalent_time, hash_password, verify_password

router = APIRouter(prefix="/account", tags=["account"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 10
MAX_PASSWORD = 128


def _normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not _EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address.")
    return value


class RegisterBody(BaseModel):
    email: str
    password: str
    display_name: str | None = Field(default=None, max_length=80)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD:
            raise ValueError(f"Use a password of at least {MIN_PASSWORD} characters.")
        if len(v) > MAX_PASSWORD:
            raise ValueError(f"Passwords can be at most {MAX_PASSWORD} characters.")
        if not v.strip():
            raise ValueError("Your password can't be only spaces.")
        return v

    @field_validator("display_name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class LoginBody(BaseModel):
    email: str
    password: str = Field(max_length=MAX_PASSWORD)


class DeleteAccountBody(BaseModel):
    password: str = Field(max_length=MAX_PASSWORD)


def serialize_student(student: Student) -> dict:
    return {
        "id": student.id,
        "email": student.email,
        "display_name": student.display_name,
        "institution_id": student.institution_id,
        "created_at": student.created_at.isoformat() if student.created_at else None,
    }


def _too_many(seconds: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "status": "rate_limited",
            "message": "Too many attempts. Please wait a few minutes and try again.",
        },
        headers={"Retry-After": str(seconds)},
    )


@router.post("/register", status_code=201, dependencies=[Depends(require_csrf_header)])
def register(
    body: RegisterBody, request: Request, response: Response, db: Session = Depends(get_db)
):
    ip = client_address(request)
    wait = rate_limit.register_by_ip.retry_after(ip)
    if wait:
        raise _too_many(wait)
    rate_limit.register_by_ip.hit(ip)

    if body.password.strip().lower() == body.email:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "validation_error",
                "message": "Choose a password that isn't your email address.",
                "errors": [{"field": "password", "message": "Too easy to guess."}],
            },
        )

    if db.scalar(select(Student).where(Student.email == body.email)) is not None:
        raise _email_taken()

    student = Student(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    db.add(student)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _email_taken()

    timeline.record_event(
        db,
        student.id,
        timeline.NOTEBOOK_STARTED,
        "Started your Fork notebook.",
    )
    start_session(db, student, response)
    db.commit()
    return {"student": serialize_student(student)}


def _email_taken() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "status": "email_taken",
            "message": "An account with that email already exists. Try signing in.",
            "errors": [{"field": "email", "message": "Already registered."}],
        },
    )


@router.post("/login", dependencies=[Depends(require_csrf_header)])
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_address(request)
    try:
        email = _normalize_email(body.email)
    except ValueError:
        email = body.email.strip().lower()[:254]

    wait = rate_limit.login_by_ip.retry_after(ip) or rate_limit.failed_login_by_email.retry_after(
        email
    )
    if wait:
        raise _too_many(wait)
    rate_limit.login_by_ip.hit(ip)

    student = db.scalar(select(Student).where(Student.email == email))
    if student is None:
        burn_equivalent_time(body.password)
        ok = False
    else:
        ok = verify_password(body.password, student.password_hash)

    if not ok:
        rate_limit.failed_login_by_email.hit(email)
        # One message for both cases, so the form can't be used to find out
        # who has an account.
        raise HTTPException(
            status_code=401,
            detail={
                "status": "invalid_credentials",
                "message": "That email and password don't match an account.",
            },
        )

    rate_limit.failed_login_by_email.reset(email)
    start_session(db, student, response)
    db.commit()
    return {"student": serialize_student(student)}


@router.post("/logout", dependencies=[Depends(require_csrf_header)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    end_session(db, request, response)
    db.commit()
    return {"status": "signed_out"}


@router.get("/me")
def me(student: Student = Depends(current_student)):
    return {"student": serialize_student(student)}


@router.delete("", dependencies=[Depends(require_csrf_header)])
def delete_account(
    body: DeleteAccountBody,
    response: Response,
    student: Student = Depends(current_student),
    db: Session = Depends(get_db),
):
    """Permanently delete the account and everything in its record.

    Asks for the password again: this can't be undone, and a borrowed
    signed-in laptop shouldn't be enough to do it.
    """
    if not verify_password(body.password, student.password_hash):
        raise HTTPException(
            status_code=403,
            detail={
                "status": "invalid_credentials",
                "message": "That password isn't right, so nothing was deleted.",
            },
        )

    stored_keys = [
        key
        for key in db.scalars(
            select(AcademicDocument.storage_key).where(
                AcademicDocument.student_id == student.id,
                AcademicDocument.storage_key.is_not(None),
            )
        )
        if key
    ]

    db.delete(student)
    db.commit()

    # Files after the rows: if a file removal fails the record is still gone,
    # and an orphaned file is reported in logs rather than leaving a
    # half-deleted account behind.
    if stored_keys:
        try:
            storage = get_storage()
        except StorageUnavailable:
            storage = None
        if storage is not None:
            for key in stored_keys:
                try:
                    storage.delete(key)
                except Exception:  # noqa: BLE001
                    import logging

                    logging.getLogger("fork.accounts").exception(
                        "Could not remove stored file during account deletion"
                    )

    clear_cookie(response)
    return {"status": "deleted"}
