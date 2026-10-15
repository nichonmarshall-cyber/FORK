"""The read-only demo notebook."""

import pytest

from tests.notebook_support import CSRF, PASSWORD, new_client, register, signed_in

pytestmark = pytest.mark.usefixtures("notebook_db")


def demo_client():
    client = new_client()
    response = client.post("/account/demo", headers=CSRF)
    assert response.status_code == 200, response.text
    assert response.json()["student"]["is_demo"] is True
    return client


def test_demo_signs_in_to_a_full_fictional_record():
    client = demo_client()
    data = client.get("/notebook").json()
    assert data["student"]["display_name"] == "Jordan (demo)"
    assert data["has_record"] is True
    assert data["snapshot"]["gpa"]["provenance"] == "confirmed_document"
    assert data["snapshot"]["credits_completed"]["value"] == 75
    assert data["snapshot"]["applicable_credits"][0]["provenance"] == "what_if"
    assert len(data["scenarios"]) == 4
    assert len(data["timeline"]) >= 10
    kinds = {d["doc_type"] for d in data["documents"]}
    assert {"degree_audit", "what_if_audit", "advising_note"} <= kinds
    # Exactly one plan, and it's the latest decision.
    assert [s["decision"] for s in data["scenarios"] if s["decision"]] == ["computer_science"]
    # Spans more than one academic year.
    dates = sorted(e["occurred_at"] for e in data["timeline"])
    assert dates[0][:4] == "2025" and dates[-1][:4] == "2026"


def test_demo_comparisons_are_real_engine_output():
    """The story is fictional; the arithmetic isn't."""
    client = demo_client()
    for scenario in client.get("/notebook").json()["scenarios"]:
        inputs = scenario["inputs"]
        for option in scenario["outcome"]["options"]:
            given = next(o for o in inputs["options"] if o["major"] == option["major_key"])
            calc = client.post(
                "/decision-paths/change-major/calculate",
                json={
                    "current_major": inputs["current_major"],
                    "prospective_major": option["major_key"],
                    "credits_completed": inputs["credits_completed"]["value"],
                    "credits_transferable": given["credits_transferable"],
                    "credits_in_progress": inputs["credits_in_progress"],
                },
            ).json()
            assert option["summary"] == calc["summary"]


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("put", "/notebook/profile", {"gpa": 1.0}),
        ("post", "/notebook/documents", {"doc_type": "other", "title": "x"}),
        ("post", "/notebook/scenarios", {
            "current_major": "computer_science",
            "credits_completed": 10,
            "options": [{"major": "information_technology", "credits_transferable": 5}],
        }),
        ("post", "/notebook/documents/from-audit", {"audit_session_id": "x"}),
    ],
)
def test_demo_refuses_every_change(method, path, body):
    client = demo_client()
    before = client.get("/notebook").json()
    response = getattr(client, method)(path, json=body, headers=CSRF)
    assert response.status_code == 403
    assert response.json()["detail"]["status"] == "demo_read_only"
    assert client.get("/notebook").json() == before


def test_demo_refuses_changes_to_existing_items_and_deletion():
    client = demo_client()
    data = client.get("/notebook").json()
    scenario_id = data["scenarios"][0]["id"]
    document_id = data["documents"][0]["id"]
    assert client.patch(
        f"/notebook/scenarios/{scenario_id}", json={"decision": None}, headers=CSRF
    ).status_code == 403
    assert client.delete(f"/notebook/scenarios/{scenario_id}", headers=CSRF).status_code == 403
    assert client.delete(f"/notebook/documents/{document_id}", headers=CSRF).status_code == 403
    assert client.post(f"/notebook/scenarios/{scenario_id}/refresh", headers=CSRF).status_code == 403
    assert client.request("DELETE", "/account", json={"password": "x"}, headers=CSRF).status_code == 403
    # Signing out is fine.
    assert client.post("/account/logout", headers=CSRF).status_code == 200


def test_demo_has_no_password_and_its_email_cannot_be_registered():
    from notebook.demo import DEMO_EMAIL

    demo_client()
    login = new_client().post(
        "/account/login", json={"email": DEMO_EMAIL, "password": PASSWORD}, headers=CSRF
    )
    assert login.status_code == 401
    assert register(new_client(), DEMO_EMAIL).status_code == 422


def test_demo_is_isolated_from_real_students():
    demo_client()
    real = signed_in("real@example.edu")
    data = real.get("/notebook").json()
    assert data["documents"] == [] and data["scenarios"] == []
    assert data["student"]["is_demo"] is False


def test_demo_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("FORK_DEMO", "false")
    assert new_client().post("/account/demo", headers=CSRF).status_code == 404


def test_rebuild_replaces_the_demo_and_keeps_one():
    from sqlalchemy import func, select

    from db.config import session_factory
    from db.models import Student
    from notebook.demo import rebuild_demo

    with session_factory()() as db:
        first = rebuild_demo(db).id
        second = rebuild_demo(db).id
        count = db.scalar(select(func.count()).select_from(Student).where(Student.is_demo.is_(True)))
    assert first != second and count == 1
