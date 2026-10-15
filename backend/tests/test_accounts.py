"""Student accounts: registration, sign-in, sessions, deletion."""

import pytest
from sqlalchemy import func, select

from tests.notebook_support import (
    CSRF,
    PASSWORD,
    new_client,
    register,
    save_audit,
    signed_in,
    upload_confirmed,
)

pytestmark = pytest.mark.usefixtures("notebook_db")


def _count(model):
    from db.config import session_factory

    with session_factory()() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_register_signs_in_and_starts_the_notebook():
    client = new_client()
    response = register(client, "  Student@Example.edu ", display_name="Sam")
    assert response.status_code == 201
    assert response.json()["student"]["email"] == "student@example.edu"
    assert "fork_session" in response.cookies

    me = client.get("/account/me")
    assert me.status_code == 200
    assert me.json()["student"]["display_name"] == "Sam"

    timeline = client.get("/notebook/timeline").json()["events"]
    assert [e["event_type"] for e in timeline] == ["notebook_started"]


def test_password_and_token_are_never_stored_in_the_clear():
    from db.config import session_factory
    from db.models import AuthSession, Student

    client = new_client()
    register(client, "a@example.edu")
    token = client.cookies.get("fork_session")
    with session_factory()() as db:
        student = db.scalar(select(Student))
        session = db.scalar(select(AuthSession))
    assert PASSWORD not in student.password_hash
    assert student.password_hash.startswith("scrypt$")
    assert session.token_hash != token
    assert len(session.token_hash) == 64


@pytest.mark.parametrize(
    "email,password,message",
    [
        ("not-an-email", PASSWORD, "valid email"),
        ("a@example.edu", "short", "at least 10"),
        ("a@example.edu", "          ", "only spaces"),
    ],
)
def test_registration_validation(email, password, message):
    response = register(new_client(), email, password)
    assert response.status_code == 422
    assert message in response.json()["detail"]["message"]


def test_password_equal_to_email_is_refused():
    response = register(new_client(), "longname@example.edu", "longname@example.edu")
    assert response.status_code == 422


def test_duplicate_email_is_refused_case_insensitively():
    register(new_client(), "dup@example.edu")
    response = register(new_client(), "DUP@example.edu")
    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "email_taken"


def test_state_changing_requests_need_the_csrf_header():
    client = new_client()
    response = client.post(
        "/account/register", json={"email": "x@example.edu", "password": PASSWORD}
    )
    assert response.status_code == 403
    assert _count_students() == 0


def _count_students():
    from db.models import Student

    return _count(Student)


def test_login_logout_and_token_revocation():
    register(new_client(), "c@example.edu")

    client = new_client()
    bad = client.post(
        "/account/login", json={"email": "c@example.edu", "password": "wrong password"}, headers=CSRF
    )
    assert bad.status_code == 401
    unknown = client.post(
        "/account/login", json={"email": "nobody@example.edu", "password": PASSWORD}, headers=CSRF
    )
    # Same answer either way, so the form can't enumerate accounts.
    assert unknown.status_code == 401
    assert unknown.json() == bad.json()

    ok = client.post(
        "/account/login", json={"email": "C@example.edu", "password": PASSWORD}, headers=CSRF
    )
    assert ok.status_code == 200
    token = client.cookies.get("fork_session")
    assert client.get("/account/me").status_code == 200

    client.post("/account/logout", headers=CSRF)
    assert client.get("/account/me").status_code == 401

    # The old token is dead server-side, not just forgotten by the browser.
    replay = new_client()
    replay.cookies.set("fork_session", token)
    assert replay.get("/account/me").status_code == 401


def test_signed_in_hint_cookie_carries_no_secret_and_clears_on_logout():
    client = new_client()
    response = register(client, "hint@example.edu")
    set_cookies = response.headers.get_list("set-cookie")
    hint = next(c for c in set_cookies if c.startswith("fork_signed_in="))
    session = next(c for c in set_cookies if c.startswith("fork_session="))
    assert hint.startswith("fork_signed_in=1;")
    assert "httponly" not in hint.lower()
    assert "httponly" in session.lower()
    assert "samesite=lax" in session.lower()

    # The hint alone authenticates nothing.
    impostor = new_client()
    impostor.cookies.set("fork_signed_in", "1")
    assert impostor.get("/account/me").status_code == 401

    logout = client.post("/account/logout", headers=CSRF)
    cleared = " ".join(logout.headers.get_list("set-cookie"))
    assert 'fork_signed_in=""' in cleared or "fork_signed_in=;" in cleared


def test_expired_session_is_rejected():
    from datetime import datetime, timedelta, timezone

    from db.config import session_factory
    from db.models import AuthSession

    client = signed_in("exp@example.edu")
    with session_factory()() as db:
        session = db.scalar(select(AuthSession))
        session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert client.get("/account/me").status_code == 401
    assert _count(AuthSession) == 0


def test_failed_logins_are_rate_limited_per_account():
    register(new_client(), "rl@example.edu")
    client = new_client()
    statuses = [
        client.post(
            "/account/login",
            json={"email": "rl@example.edu", "password": "nope nope nope"},
            headers={**CSRF, "X-Forwarded-For": f"10.0.0.{i}"},
        ).status_code
        for i in range(10)
    ]
    assert statuses[:8] == [401] * 8
    assert statuses[8] == 429
    # Even the right password waits until the window passes.
    right = client.post(
        "/account/login", json={"email": "rl@example.edu", "password": PASSWORD}, headers=CSRF
    )
    assert right.status_code == 429
    assert "Retry-After" in right.headers


def test_notebook_requires_sign_in():
    client = new_client()
    assert client.get("/notebook").status_code == 401
    assert client.get("/notebook/timeline").status_code == 401
    assert client.put("/notebook/profile", json={"gpa": 3.0}, headers=CSRF).status_code == 401


def test_delete_account_needs_the_password_and_removes_everything(audit_pdf):
    from db.models import (
        AcademicDocument,
        AcademicFact,
        AuthSession,
        SavedScenario,
        Student,
        TimelineEvent,
    )

    keeper = signed_in("keeper@example.edu")
    keeper.put("/notebook/profile", json={"gpa": 3.1}, headers=CSRF)

    client = signed_in("leaver@example.edu")
    sid = upload_confirmed(client, "unt_audit_standard.txt")
    assert save_audit(client, sid).status_code == 200
    client.put("/notebook/profile", json={"gpa": 3.5}, headers=CSRF)
    client.post(
        "/notebook/scenarios",
        json={
            "current_major": "computer_science",
            "credits_completed": 81,
            "credits_in_progress": 18,
            "options": [{"major": "information_technology", "credits_transferable": 70}],
        },
        headers=CSRF,
    )

    wrong = client.request(
        "DELETE", "/account", json={"password": "not my password"}, headers=CSRF
    )
    assert wrong.status_code == 403
    assert _count(Student) == 2

    gone = client.request("DELETE", "/account", json={"password": PASSWORD}, headers=CSRF)
    assert gone.status_code == 200
    assert client.get("/account/me").status_code == 401

    # Only the keeper's rows remain.
    assert _count(Student) == 1
    assert _count(AcademicDocument) == 0
    assert _count(SavedScenario) == 0
    assert _count(AcademicFact) == 1
    assert _count(TimelineEvent) == 2  # keeper: started + facts_updated
    assert _count(AuthSession) == 1
    assert keeper.get("/notebook").status_code == 200
