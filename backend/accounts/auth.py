"""
Session tokens and the `current_student` dependency.

A signed-in browser holds a random token in an HttpOnly cookie; the database
holds only its SHA-256. The cookie is first-party: the frontend proxies
`/api/fork/*` to this backend (see frontend/next.config.ts), so the browser
only ever talks to the frontend's own origin and the cookie is never a
third-party cookie that Safari or a privacy setting would drop.

Cross-site request forgery is covered twice. SameSite=Lax keeps the cookie off
cross-site POSTs, and every state-changing account or notebook request must
carry an `X-Fork-CSRF` header, which a cross-origin page cannot add without a
CORS preflight this API never grants.
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.config import get_db
from db.models import AuthSession, Student

COOKIE_NAME = "fork_session"
#: Readable by page scripts and carries no secret -- only "1". Lets the
#: frontend skip an identity request for visitors who have never signed in.
#: The server never trusts it; every request is authenticated by the
#: HttpOnly session cookie above.
HINT_COOKIE_NAME = "fork_signed_in"
CSRF_HEADER = "X-Fork-CSRF"
SESSION_LIFETIME = timedelta(days=14)
#: How often last_seen_at is written. Writing it on every request would turn
#: every read into a write.
_TOUCH_INTERVAL = timedelta(minutes=10)


def _cookie_secure() -> bool:
    # Secure by default. Set FORK_COOKIE_SECURE=false only for local HTTP
    # development in a browser that refuses Secure cookies on localhost.
    return os.environ.get("FORK_COOKIE_SECURE", "true").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    # SQLite hands timestamps back without a zone; everything is written UTC.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


#: A demo visit is a look around, not a stay.
DEMO_SESSION_LIFETIME = timedelta(hours=2)


def start_session(
    db: Session, student: Student, response: Response, lifetime: timedelta = SESSION_LIFETIME
) -> None:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.add(
        AuthSession(
            student_id=student.id,
            token_hash=hash_token(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + lifetime,
        )
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        HINT_COOKIE_NAME,
        "1",
        max_age=int(lifetime.total_seconds()),
        httponly=False,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


def end_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        if session is not None:
            db.delete(session)
    clear_cookie(response)


def clear_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=_cookie_secure(), httponly=True, samesite="lax"
    )
    response.delete_cookie(
        HINT_COOKIE_NAME, path="/", secure=_cookie_secure(), httponly=False, samesite="lax"
    )


def _not_signed_in() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"status": "not_authenticated", "message": "Please sign in to continue."},
    )


def current_student(request: Request, db: Session = Depends(get_db)) -> Student:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise _not_signed_in()

    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    now = datetime.now(timezone.utc)
    if session is None:
        raise _not_signed_in()
    if _aware(session.expires_at) <= now:
        db.delete(session)
        db.commit()
        raise _not_signed_in()

    if now - _aware(session.last_seen_at) > _TOUCH_INTERVAL:
        session.last_seen_at = now
        db.commit()

    student = db.get(Student, session.student_id)
    if student is None:
        raise _not_signed_in()
    return student


def require_writable(student: Student = Depends(current_student)) -> Student:
    """Refuse changes to the shared demo notebook.

    Applied alongside the CSRF check on every state-changing notebook and
    account route. FastAPI resolves current_student once per request, so this
    costs no extra lookup.
    """
    if student.is_demo:
        raise HTTPException(
            status_code=403,
            detail={
                "status": "demo_read_only",
                "message": "This is a demo notebook for a fictional student, so it "
                "can't be changed. Create a free account to build your own.",
            },
        )
    return student


def require_csrf_header(request: Request) -> None:
    """Applied to every state-changing account and notebook route."""
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(
            status_code=403,
            detail={
                "status": "csrf_header_missing",
                "message": "This request is missing Fork's request header.",
            },
        )


def client_address(request: Request) -> str:
    """Best-effort client address for rate limiting.

    Requests arrive through the frontend's proxy, so the first X-Forwarded-For
    entry is the browser. That header can be forged by a client calling the
    backend directly, which is why failed logins are also limited per account.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"
