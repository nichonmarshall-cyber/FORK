"""
The academic notebook: record, documents, saved comparisons, timeline.

Grouped by the promise each test protects:
  * the dashboard shows only what the record supports, and says where from
  * document-backed figures can't be silently replaced by typed ones
  * a saved comparison is recalculated server-side and labelled by evidence
  * the timeline records meaningful changes and nothing else
  * one student can never see or touch another student's record
"""

import pytest

from tests.notebook_support import (
    CSRF,
    events,
    new_client,
    save_audit,
    signed_in,
    upload_confirmed,
)

pytestmark = pytest.mark.usefixtures("notebook_db")

AUDIT_SOURCE = "UNT Degree Audit, confirmed by you"


def _scenario(client, **overrides):
    body = {
        "current_major": "computer_science",
        "credits_completed": 81,
        "credits_in_progress": 18,
        "credits_source": AUDIT_SOURCE,
        "options": [{"major": "information_technology", "credits_transferable": 70}],
    }
    body.update(overrides)
    return client.post("/notebook/scenarios", json=body, headers=CSRF)


# --- empty and populated dashboard --------------------------------------


def test_new_student_sees_an_empty_record_with_next_steps():
    client = signed_in("new@example.edu")
    data = client.get("/notebook").json()

    assert data["has_record"] is False
    assert data["documents"] == []
    assert data["scenarios"] == []
    snapshot = data["snapshot"]
    assert snapshot["institution"]["name"] == "University of North Texas"
    for field in ("current_major", "gpa", "credits_completed", "credits_remaining_current"):
        assert snapshot[field] is None
    assert snapshot["graduation"]["status"] == "not_projected"

    step_ids = [s["id"] for s in data["next_steps"]]
    assert step_ids[:3] == ["add_degree_audit", "set_current_major", "first_comparison"]
    assert "add_gpa" in step_ids
    assert data["storage"]["raw_files_enabled"] is False


def test_reading_the_dashboard_never_writes_history():
    client = signed_in("reader@example.edu")
    before = events(client)
    for _ in range(3):
        client.get("/notebook")
        client.get("/notebook/timeline")
    assert events(client) == before


def test_confirmed_audit_populates_the_snapshot_with_document_provenance():
    client = signed_in("audit@example.edu")
    sid = upload_confirmed(client, "unt_audit_standard.txt")
    response = save_audit(client, sid)
    assert response.status_code == 200, response.text
    assert response.json()["created"] is True
    document = response.json()["document"]

    assert document["doc_type"] == "degree_audit"
    assert document["status"] == "confirmed"
    assert document["read_by_fork"] is True
    assert document["program_key"] == "computer_science"
    assert document["file"]["stored"] is False
    assert document["summary"]["completed_hours"] == 81.0
    assert document["summary"]["degree_hours"] == {"earned": 81.0, "needed": 21.0, "in_progress": 18.0}
    assert "fingerprint" not in document["summary"]
    linked = {f["key"] for f in document["linked_facts"]}
    assert {"credits_completed", "credits_in_progress", "catalog_year", "current_major"} <= linked

    snapshot = client.get("/notebook").json()["snapshot"]
    completed = snapshot["credits_completed"]
    assert completed["value"] == 81
    assert completed["provenance"] == "confirmed_document"
    assert completed["source_label"] == AUDIT_SOURCE
    assert completed["source_date"] == "08/18/2026 03:18 PM"
    assert completed["document_id"] == document["id"]
    assert snapshot["current_major"]["value"] == "computer_science"
    assert snapshot["current_major"]["display"] == "Computer Science"
    assert snapshot["catalog_year"]["value"] == "Fall 2024"
    # Never presented as verified with the university.
    assert "verified" not in completed["provenance_label"].lower()


def test_derived_credits_remaining_matches_the_engine():
    """The dashboard's one derived figure must agree with what a comparison
    would show for the same facts, or the two screens contradict each other."""
    client = signed_in("derived@example.edu")
    save_audit(client, upload_confirmed(client, "unt_audit_standard.txt"))
    remaining = client.get("/notebook").json()["snapshot"]["credits_remaining_current"]
    assert remaining["provenance"] == "derived"

    calc = client.post(
        "/decision-paths/change-major/calculate",
        json={
            "current_major": "computer_science",
            "prospective_major": "information_technology",
            "credits_completed": 81,
            "credits_transferable": 70,
        },
    ).json()
    engine_value = next(
        li["value"]
        for li in calc["comparison"]["staying"]["line_items"]
        if li["label"].startswith("Credits still needed")
    )
    assert remaining["value"] == engine_value
    assert set(remaining["inputs_provenance"]) == {"confirmed_document"}


def test_unconfirmed_audit_cannot_be_saved():
    from tests.notebook_support import fixture_pdf

    client = signed_in("unconfirmed@example.edu")
    sid = client.post(
        "/audit/unt/upload",
        files={"file": ("a.pdf", fixture_pdf("unt_audit_standard.txt"), "application/pdf")},
    ).json()["session_id"]
    response = save_audit(client, sid)
    assert response.status_code == 409
    assert client.get("/notebook").json()["documents"] == []


def test_saving_the_same_audit_twice_does_not_duplicate_it():
    client = signed_in("twice@example.edu")
    sid = upload_confirmed(client, "unt_audit_standard.txt")
    first = save_audit(client, sid).json()
    second = save_audit(client, sid).json()
    assert second["created"] is False
    assert second["document"]["id"] == first["document"]["id"]
    assert [e["event_type"] for e in events(client)].count("audit_added") == 1


def test_a_newer_audit_supersedes_the_old_one_and_its_facts():
    client = signed_in("newer@example.edu")
    first = save_audit(client, upload_confirmed(client, "unt_audit_standard.txt")).json()
    second = save_audit(client, upload_confirmed(client, "synthetic_current_cs.txt")).json()
    assert second["created"] is True

    data = client.get("/notebook").json()
    statuses = {d["id"]: d["status"] for d in data["documents"]}
    assert statuses[first["document"]["id"]] == "superseded"
    assert statuses[second["document"]["id"]] == "confirmed"
    assert data["snapshot"]["credits_completed"]["document_id"] == second["document"]["id"]
    assert data["snapshot"]["credits_completed"]["source_date"] == "08/20/2026 04:20 PM"


# --- student-reported vs document-backed --------------------------------


def test_student_reported_facts_are_labelled_and_logged():
    client = signed_in("self@example.edu")
    response = client.put(
        "/notebook/profile",
        json={"current_major": "psychology_ba", "gpa": 3.456, "credits_completed": 40},
        headers=CSRF,
    )
    assert response.status_code == 200
    snapshot = response.json()["snapshot"]
    assert snapshot["gpa"]["value"] == 3.46
    assert snapshot["gpa"]["provenance"] == "student_reported"
    assert snapshot["credits_completed"]["provenance"] == "student_reported"
    assert snapshot["current_major"]["display"] == "Psychology (B.A.)"
    # Derived from two student-reported facts, and says so.
    assert set(snapshot["credits_remaining_current"]["inputs_provenance"]) == {"student_reported"}

    latest = events(client)[0]
    assert latest["event_type"] == "facts_updated"
    assert "own figures" in latest["summary"]

    # Unchanged values don't add history.
    client.put("/notebook/profile", json={"gpa": 3.46}, headers=CSRF)
    assert [e["event_type"] for e in events(client)].count("facts_updated") == 1

    cleared = client.put("/notebook/profile", json={"gpa": None}, headers=CSRF).json()
    assert cleared["snapshot"]["gpa"] is None


@pytest.mark.parametrize(
    "body", [{"gpa": 4.5}, {"credits_completed": -1}, {"credits_in_progress": 31}]
)
def test_profile_validation(body):
    client = signed_in("val@example.edu")
    assert client.put("/notebook/profile", json=body, headers=CSRF).status_code == 422


def test_unknown_major_is_refused():
    client = signed_in("major@example.edu")
    response = client.put("/notebook/profile", json={"current_major": "nursing"}, headers=CSRF)
    assert response.status_code == 422


def test_typed_figures_cannot_replace_document_backed_ones():
    client = signed_in("guard@example.edu")
    client.put("/notebook/profile", json={"current_major": "psychology_ba"}, headers=CSRF)
    save_audit(client, upload_confirmed(client, "unt_audit_standard.txt"))

    # The confirmed audit replaced the typed major, and the timeline says so.
    added = next(e for e in events(client) if e["event_type"] == "audit_added")
    assert added["detail"]["replaced_student_reported_major"] == "psychology_ba"

    refused = client.put(
        "/notebook/profile", json={"credits_completed": 90, "gpa": 3.2}, headers=CSRF
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["field"] == "credits_completed"
    snapshot = client.get("/notebook").json()["snapshot"]
    assert snapshot["credits_completed"]["value"] == 81
    # The batch is all-or-nothing: the GPA in the refused request wasn't saved.
    assert snapshot["gpa"] is None

    # Re-sending the same value is not a conflict.
    same = client.put("/notebook/profile", json={"credits_completed": 81}, headers=CSRF)
    assert same.status_code == 200


def test_removing_the_document_removes_the_facts_it_backed():
    client = signed_in("remove@example.edu")
    doc = save_audit(client, upload_confirmed(client, "unt_audit_standard.txt")).json()["document"]
    response = client.delete(f"/notebook/documents/{doc['id']}", headers=CSRF)
    assert response.status_code == 200
    snapshot = response.json()["snapshot"]
    assert snapshot["credits_completed"] is None
    assert snapshot["current_major"] is None
    removed = events(client)[0]
    assert removed["event_type"] == "document_removed"
    assert "credits_completed" in removed["detail"]["removed_facts"]
    # History of the add survives, unlinked from the deleted document.
    added = next(e for e in events(client) if e["event_type"] == "audit_added")
    assert added["document_id"] is None

    # And now a typed figure is allowed again.
    assert client.put(
        "/notebook/profile", json={"credits_completed": 85}, headers=CSRF
    ).status_code == 200


# --- What-If documents ---------------------------------------------------


def test_what_if_audit_is_scoped_to_its_own_program():
    client = signed_in("whatif@example.edu")
    sid = upload_confirmed(client, "synthetic_current_cs.txt")
    upload_confirmed(client, "synthetic_whatif_psyc.txt", session_id=sid)
    save_audit(client, sid)
    response = save_audit(client, sid, "what_if")
    assert response.status_code == 200, response.text
    document = response.json()["document"]
    assert document["doc_type"] == "what_if_audit"
    assert document["program_key"] == "psychology_bs"
    assert document["summary"]["supplies_applicable_credits"] is True

    snapshot = client.get("/notebook").json()["snapshot"]
    applicable = snapshot["applicable_credits"]
    assert len(applicable) == 1
    assert applicable[0]["scope"] == "psychology_bs"
    assert applicable[0]["provenance"] == "what_if"
    assert applicable[0]["value"] == 81
    # The What-If says nothing about the student's own completed hours.
    assert snapshot["credits_completed"]["provenance"] == "confirmed_document"
    assert events(client)[0]["event_type"] == "what_if_added"


def test_what_if_needing_acknowledgement_is_saved_without_a_figure():
    """The real pair disagrees on dates; until acknowledged, the compare form
    refuses the What-If figure, so the notebook must too."""
    client = signed_in("ack@example.edu")
    sid = upload_confirmed(client, "unt_audit_standard.txt")
    upload_confirmed(client, "unt_audit_whatif.txt", session_id=sid)
    document = save_audit(client, sid, "what_if").json()["document"]
    assert document["summary"]["supplies_applicable_credits"] is False
    assert document["summary"]["unresolved"]
    assert client.get("/notebook").json()["snapshot"]["applicable_credits"] == []


# --- documents the student records ---------------------------------------


def test_recorded_documents_are_honest_about_not_being_read():
    client = signed_in("rec@example.edu")
    response = client.post(
        "/notebook/documents",
        json={"doc_type": "transcript", "title": "Unofficial transcript", "document_date": "2026-09-01"},
        headers=CSRF,
    )
    assert response.status_code == 201
    document = response.json()["document"]
    assert document["status"] == "recorded"
    assert document["read_by_fork"] is False
    assert document["linked_facts"] == []
    assert "not read" in document["status_label"].lower()
    assert events(client)[0]["event_type"] == "document_recorded"
    # A recorded transcript changes no academic figure.
    assert client.get("/notebook").json()["snapshot"]["credits_completed"] is None


@pytest.mark.parametrize(
    "body,status",
    [
        ({"doc_type": "degree_audit", "title": "My audit"}, 400),
        ({"doc_type": "transcript", "title": "   "}, 400),
        ({"doc_type": "transcript", "title": "T", "document_date": "Sept 1"}, 400),
    ],
)
def test_recorded_document_validation(body, status):
    client = signed_in("recval@example.edu")
    assert client.post("/notebook/documents", json=body, headers=CSRF).status_code == status


def test_file_upload_is_refused_when_storage_is_off():
    client = signed_in("nofile@example.edu")
    doc = client.post(
        "/notebook/documents", json={"doc_type": "catalog", "title": "CS catalog"}, headers=CSRF
    ).json()["document"]
    response = client.post(
        f"/notebook/documents/{doc['id']}/file",
        files={"file": ("c.pdf", b"%PDF-1.4 test", "application/pdf")},
        headers=CSRF,
    )
    assert response.status_code == 501
    assert "doesn't keep original files" in response.json()["detail"]["message"]


def test_local_storage_round_trip_and_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv("FORK_DOCUMENT_STORAGE", "local")
    monkeypatch.setenv("FORK_DOCUMENT_STORAGE_DIR", str(tmp_path))
    client = signed_in("files@example.edu")
    assert client.get("/notebook").json()["storage"]["raw_files_enabled"] is True

    doc = client.post(
        "/notebook/documents", json={"doc_type": "advising_note", "title": "Advisor notes"}, headers=CSRF
    ).json()["document"]
    upload = client.post(
        f"/notebook/documents/{doc['id']}/file",
        files={"file": ("notes.txt", b"ask about CSCE 3110", "text/plain")},
        headers=CSRF,
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["document"]["file"]["stored"] is True
    stored = list(tmp_path.rglob("*.txt"))
    assert len(stored) == 1

    download = client.get(f"/notebook/documents/{doc['id']}/file")
    assert download.status_code == 200
    assert download.content == b"ask about CSCE 3110"
    assert download.headers["cache-control"] == "private, no-store"

    bad_type = client.post(
        f"/notebook/documents/{doc['id']}/file",
        files={"file": ("x.exe", b"MZ", "application/x-msdownload")},
        headers=CSRF,
    )
    assert bad_type.status_code == 415

    client.delete(f"/notebook/documents/{doc['id']}", headers=CSRF)
    assert list(tmp_path.rglob("*.txt")) == []
    # No empty per-student folder is left behind either.
    assert list(tmp_path.iterdir()) == []


# --- saved comparisons ----------------------------------------------------


def test_saved_comparison_is_recalculated_and_matches_the_engine():
    client = signed_in("scen@example.edu")
    response = _scenario(client, credits_source="Student-reported")
    assert response.status_code == 201, response.text
    scenario = response.json()["scenario"]

    calc = client.post(
        "/decision-paths/change-major/calculate",
        json={
            "current_major": "computer_science",
            "prospective_major": "information_technology",
            "credits_completed": 81,
            "credits_transferable": 70,
            "credits_in_progress": 18,
        },
    ).json()
    option = scenario["outcome"]["options"][0]
    assert option["status"] == "calculated"
    assert option["summary"] == calc["summary"]
    assert scenario["outcome_provenance"] == "derived"
    assert scenario["title"] == "Compared Computer Science with Information Technology"
    assert events(client)[0]["event_type"] == "comparison_saved"


def test_a_client_cannot_post_its_own_result():
    client = signed_in("forge@example.edu")
    response = _scenario(client, outcome={"options": [{"summary": {"incremental_tuition": 1}}]})
    assert response.status_code == 201
    assert response.json()["scenario"]["outcome"]["options"][0]["summary"]["incremental_tuition"] != 1


def test_document_label_is_kept_only_when_the_record_backs_it():
    client = signed_in("prov@example.edu")
    # No audit anywhere: the claim can't be backed.
    claimed = _scenario(client).json()["scenario"]
    completed = claimed["inputs"]["credits_completed"]
    assert completed["provenance"] == "student_reported"
    assert "doesn't match" in completed["note"]
    # The engine's own line items carry the downgraded label, not the claim.
    line = claimed["outcome"]["options"][0]["line_items"]["credits_transferable"]
    assert line["source"] != AUDIT_SOURCE

    save_audit(client, upload_confirmed(client, "unt_audit_standard.txt"))
    backed = _scenario(client).json()["scenario"]["inputs"]["credits_completed"]
    assert backed["provenance"] == "confirmed_document"
    assert backed["document_id"] is not None

    mismatched = _scenario(client, credits_completed=90).json()["scenario"]
    assert mismatched["inputs"]["credits_completed"]["provenance"] == "student_reported"


def test_audit_confirmed_this_visit_backs_a_comparison_before_it_is_saved():
    client = signed_in("visit@example.edu")
    sid = upload_confirmed(client, "unt_audit_standard.txt")
    scenario = _scenario(client, audit_session_id=sid).json()["scenario"]
    completed = scenario["inputs"]["credits_completed"]
    assert completed["provenance"] == "confirmed_document"
    assert completed["document_id"] is None
    assert "this visit" in completed["note"]


def test_what_if_figure_is_only_labelled_what_if_for_its_own_program():
    client = signed_in("wiprov@example.edu")
    sid = upload_confirmed(client, "synthetic_current_cs.txt")
    upload_confirmed(client, "synthetic_whatif_psyc.txt", session_id=sid)
    save_audit(client, sid)
    save_audit(client, sid, "what_if")
    what_if_source = client.get("/notebook").json()["snapshot"]["applicable_credits"][0]["source_label"]

    scenario = _scenario(
        client,
        options=[
            {"major": "psychology_bs", "credits_transferable": 81, "credits_transferable_source": what_if_source},
            # Same label on another program is not backed by anything.
            {"major": "information_technology", "credits_transferable": 81, "credits_transferable_source": what_if_source},
        ],
    ).json()["scenario"]
    by_major = {o["major"]: o for o in scenario["inputs"]["options"]}
    assert by_major["psychology_bs"]["provenance"] == "what_if"
    assert by_major["information_technology"]["provenance"] == "student_reported"


def test_pending_option_is_kept_without_numbers():
    client = signed_in("pending@example.edu")
    scenario = _scenario(
        client,
        credits_source="Student-reported",
        options=[
            {"major": "information_technology", "credits_transferable": 70},
            {"major": "psychology_ba"},
        ],
    ).json()["scenario"]
    statuses = {o["major_key"]: o["status"] for o in scenario["outcome"]["options"]}
    assert statuses == {"information_technology": "calculated", "psychology_ba": "pending"}


def test_invalid_comparison_inputs_are_rejected():
    client = signed_in("bad@example.edu")
    # Transfer can't exceed completed; checked by the same model the engine
    # uses. With no option left that calculated, there's nothing to save.
    response = _scenario(
        client, options=[{"major": "information_technology", "credits_transferable": 95}]
    )
    assert response.status_code == 422
    assert "cannot exceed" in response.json()["detail"]["message"]

    # One bad option among good ones is kept, marked failed, like the
    # compare flow does.
    mixed = _scenario(
        client,
        options=[
            {"major": "information_technology", "credits_transferable": 95},
            {"major": "psychology_ba", "credits_transferable": 40},
        ],
    )
    assert mixed.status_code == 201
    statuses = {o["major_key"]: o["status"] for o in mixed.json()["scenario"]["outcome"]["options"]}
    assert statuses == {"information_technology": "failed", "psychology_ba": "calculated"}

    assert _scenario(client, current_major="nursing").status_code == 422
    assert client.get("/notebook").json()["scenarios"][0]["id"] == mixed.json()["scenario"]["id"]


def test_choosing_a_plan_is_recorded_and_exclusive():
    client = signed_in("plan@example.edu")
    first = _scenario(client, credits_source="Student-reported").json()["scenario"]
    second = _scenario(
        client,
        credits_source="Student-reported",
        options=[{"major": "psychology_ba", "credits_transferable": 50}],
    ).json()["scenario"]

    stay = client.patch(
        f"/notebook/scenarios/{first['id']}", json={"decision": "computer_science"}, headers=CSRF
    )
    assert stay.status_code == 200
    assert events(client)[0]["summary"] == "Marked staying in Computer Science as your current plan."

    switch = client.patch(
        f"/notebook/scenarios/{second['id']}", json={"decision": "psychology_ba"}, headers=CSRF
    )
    assert switch.status_code == 200
    data = client.get("/notebook").json()
    decisions = {s["id"]: s["decision"] for s in data["scenarios"]}
    assert decisions == {first["id"]: None, second["id"]: "psychology_ba"}
    assert data["timeline"][0]["event_type"] == "plan_chosen"
    assert "record_plan" not in [s["id"] for s in data["next_steps"]]

    invalid = client.patch(
        f"/notebook/scenarios/{second['id']}", json={"decision": "business_administration"}, headers=CSRF
    )
    assert invalid.status_code == 400

    cleared = client.patch(f"/notebook/scenarios/{second['id']}", json={"decision": None}, headers=CSRF)
    assert cleared.status_code == 200
    assert events(client)[0]["event_type"] == "plan_cleared"

    # Renaming isn't an academic event.
    count = len(events(client))
    client.patch(f"/notebook/scenarios/{second['id']}", json={"title": "Psych option"}, headers=CSRF)
    assert len(events(client)) == count


def test_refresh_downgrades_provenance_when_the_evidence_is_removed():
    client = signed_in("refresh@example.edu")
    doc = save_audit(client, upload_confirmed(client, "unt_audit_standard.txt")).json()["document"]
    scenario = _scenario(client).json()["scenario"]
    assert scenario["inputs"]["credits_completed"]["provenance"] == "confirmed_document"

    unchanged = client.post(f"/notebook/scenarios/{scenario['id']}/refresh", headers=CSRF).json()
    assert unchanged["changed"] is False

    client.delete(f"/notebook/documents/{doc['id']}", headers=CSRF)
    refreshed = client.post(f"/notebook/scenarios/{scenario['id']}/refresh", headers=CSRF).json()
    assert refreshed["changed"] is True
    assert refreshed["scenario"]["inputs"]["credits_completed"]["provenance"] == "student_reported"
    assert events(client)[0]["event_type"] == "comparison_updated"


def test_estimated_transfer_figures_become_advisor_next_steps():
    client = signed_in("steps@example.edu")
    save_audit(client, upload_confirmed(client, "unt_audit_standard.txt"))
    _scenario(client, options=[{"major": "psychology_ba", "credits_transferable": 40}])
    steps = {s["id"]: s for s in client.get("/notebook").json()["next_steps"]}
    assert "what_if_psychology_ba" in steps
    assert "add_degree_audit" not in steps
    assert "first_comparison" not in steps
    assert "record_plan" in steps


def test_deleting_a_scenario_keeps_its_history():
    client = signed_in("del@example.edu")
    scenario = _scenario(client, credits_source="Student-reported").json()["scenario"]
    assert client.delete(f"/notebook/scenarios/{scenario['id']}", headers=CSRF).status_code == 200
    history = events(client)
    assert history[0]["event_type"] == "comparison_removed"
    saved = next(e for e in history if e["event_type"] == "comparison_saved")
    assert saved["scenario_id"] is None


# --- isolation -------------------------------------------------------------


def test_students_cannot_reach_each_others_records(tmp_path, monkeypatch):
    monkeypatch.setenv("FORK_DOCUMENT_STORAGE", "local")
    monkeypatch.setenv("FORK_DOCUMENT_STORAGE_DIR", str(tmp_path))

    alice = signed_in("alice@example.edu")
    sid = upload_confirmed(alice, "unt_audit_standard.txt")
    doc = save_audit(alice, sid).json()["document"]
    note = alice.post(
        "/notebook/documents", json={"doc_type": "advising_note", "title": "Private"}, headers=CSRF
    ).json()["document"]
    alice.post(
        f"/notebook/documents/{note['id']}/file",
        files={"file": ("n.txt", b"private", "text/plain")},
        headers=CSRF,
    )
    scenario = _scenario(alice).json()["scenario"]
    alice.put("/notebook/profile", json={"gpa": 3.9}, headers=CSRF)

    bob = signed_in("bob@example.edu")
    bob_view = bob.get("/notebook").json()
    assert bob_view["documents"] == []
    assert bob_view["scenarios"] == []
    assert bob_view["snapshot"]["gpa"] is None
    assert [e["event_type"] for e in bob_view["timeline"]] == ["notebook_started"]

    # Every id-addressed route answers as though the id doesn't exist.
    assert bob.get(f"/notebook/documents/{note['id']}/file").status_code == 404
    assert bob.delete(f"/notebook/documents/{doc['id']}", headers=CSRF).status_code == 404
    assert bob.post(
        f"/notebook/documents/{note['id']}/file",
        files={"file": ("x.txt", b"overwrite", "text/plain")},
        headers=CSRF,
    ).status_code == 404
    assert bob.patch(
        f"/notebook/scenarios/{scenario['id']}", json={"decision": "computer_science"}, headers=CSRF
    ).status_code == 404
    assert bob.post(f"/notebook/scenarios/{scenario['id']}/refresh", headers=CSRF).status_code == 404
    assert bob.delete(f"/notebook/scenarios/{scenario['id']}", headers=CSRF).status_code == 404

    # Bob can't pull Alice's audit review into his own record...
    assert save_audit(bob, sid).status_code == 403
    # ...or use it to back his own comparison's provenance.
    bob_scenario = _scenario(bob, audit_session_id=sid).json()["scenario"]
    assert bob_scenario["inputs"]["credits_completed"]["provenance"] == "student_reported"

    # Alice's record is untouched by all of that.
    alice_view = alice.get("/notebook").json()
    assert len(alice_view["documents"]) == 2
    assert alice_view["scenarios"][0]["decision"] is None
    assert alice.get(f"/notebook/documents/{note['id']}/file").content == b"private"


def test_anonymous_compare_flow_still_works_without_an_account():
    client = new_client()
    response = client.post(
        "/decision-paths/change-major/calculate",
        json={
            "current_major": "computer_science",
            "prospective_major": "information_technology",
            "credits_completed": 72,
            "credits_transferable": 60,
        },
    )
    assert response.status_code == 200
