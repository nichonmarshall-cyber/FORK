"""
The notebook home: one read that assembles everything the dashboard shows.

Nothing here writes. Opening the dashboard never adds a timeline event or
changes a fact.

The snapshot shows only what the record supports. Where a figure isn't known
it is reported as missing with the reason, never as zero or a guess. The one
derived figure -- credits still needed for the current major -- uses exactly
the engine's own rule (required minus completed, floored at zero) and says
which two facts it came from.

Next steps are deterministic: each one is triggered by a specific gap or
condition in the record, and carries the reason it appears.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.models import Student

from . import documents as D
from . import facts as F
from . import provenance as P
from . import scenarios as S
from . import timeline
from .storage import storage_status

#: Matches documents.resolution.DOCUMENT_DATE_GAP_DAYS: about one term.
STALE_AUDIT_DAYS = 90


def _parse_audit_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _major_display(key: str | None, majors: dict) -> str | None:
    if key is None:
        return None
    entry = majors.get(key)
    return entry["display_name"] if entry else key


def build_snapshot(student: Student, facts: list, reference_data: dict) -> dict:
    majors = reference_data["majors"]
    by_key = {(f.key, f.scope or ""): f for f in facts}

    def fact(key, scope=""):
        found = by_key.get((key, scope))
        return F.serialize_fact(found) if found else None

    current_major = fact(F.CURRENT_MAJOR)
    if current_major:
        current_major["display"] = _major_display(current_major["value"], majors)

    applicable = []
    for (key, scope), f in sorted(by_key.items()):
        if key == F.APPLICABLE_CREDITS and scope:
            entry = F.serialize_fact(f)
            entry["display"] = _major_display(scope, majors)
            applicable.append(entry)

    completed = by_key.get((F.CREDITS_COMPLETED, ""))
    remaining = None
    if current_major and completed is not None and current_major["value"] in majors:
        major = majors[current_major["value"]]
        required = float(major["credits_required"])
        done = completed.value["value"]
        # Same rule as the engine's credits_remaining_current.
        value = max(required - done, 0.0)
        remaining = {
            "key": "credits_remaining_current",
            "value": int(value) if value == int(value) else value,
            "provenance": P.DERIVED,
            "provenance_label": P.LABELS[P.DERIVED],
            "source_label": (
                f"{int(required)} credits required for {major['display_name']} "
                f"({major['credits_required_source']}) minus {done} completed "
                f"({completed.source_label})"
            ),
            "source_date": major.get("credits_required_source_date"),
            "inputs_provenance": [current_major["provenance"], completed.provenance],
        }

    degree_hours = fact(F.DEGREE_HOURS)

    return {
        "institution": {
            "id": student.institution_id,
            "name": reference_data["institution"].get("name", student.institution_id),
        },
        "current_major": current_major,
        "program": fact(F.PROGRAM),
        "catalog_year": fact(F.CATALOG_YEAR),
        "gpa": fact(F.GPA),
        "credits_completed": fact(F.CREDITS_COMPLETED),
        "credits_in_progress": fact(F.CREDITS_IN_PROGRESS),
        "applicable_credits": applicable,
        "requirements": fact(F.REQUIREMENTS_SUMMARY),
        "degree_hours": degree_hours,
        "credits_remaining_current": remaining,
        # Fork does not project a graduation date: that depends on course
        # availability, sequencing and the student's own load, none of which
        # it models. The timeline it can stand behind is per-comparison, in
        # semesters at full-time enrollment.
        "graduation": {
            "status": "not_projected",
            "message": (
                "Fork doesn't predict a graduation date. Compare paths to see how "
                "many semesters each one needs at a full-time load."
            ),
        },
    }


def build_next_steps(
    student_id: str, facts: list, documents: list, saved: list, reference_data: dict
) -> list[dict]:
    majors = reference_data["majors"]
    by_key = {(f.key, f.scope or ""): f for f in facts}
    steps: list[dict] = []

    audits = [d for d in documents if d.doc_type == D.DEGREE_AUDIT and d.status == D.CONFIRMED]
    current_major = by_key.get((F.CURRENT_MAJOR, ""))

    if not audits:
        steps.append(
            {
                "id": "add_degree_audit",
                "title": "Add your UNT degree audit",
                "detail": (
                    "Your audit is the evidence behind your completed hours. Fork reads "
                    "it, you check its reading, and the figures you confirm become "
                    "part of your record."
                ),
                "reason": "No confirmed degree audit in your record.",
                "action": {"label": "Add a degree audit", "href": "/compare?panel=audit"},
            }
        )
    else:
        latest = audits[0]
        prepared = _parse_audit_date(latest.document_date)
        if prepared is not None:
            age = (datetime.now(timezone.utc) - prepared).days
            if age > STALE_AUDIT_DAYS:
                steps.append(
                    {
                        "id": "refresh_degree_audit",
                        "title": "Run a fresh degree audit",
                        "detail": (
                            f"Your audit was prepared {latest.document_date}, about "
                            f"{age // 30} months ago. Grades posted since then won't be "
                            "in it."
                        ),
                        "reason": f"Latest audit is more than {STALE_AUDIT_DAYS} days old.",
                        "action": {"label": "Add a newer audit", "href": "/compare?panel=audit"},
                    }
                )

    if current_major is None:
        steps.append(
            {
                "id": "set_current_major",
                "title": "Tell Fork your current major",
                "detail": "Comparisons are measured from the major you're in now.",
                "reason": "No current major in your record.",
                "action": {"label": "Update your details", "href": "/#record-details"},
            }
        )

    if not saved:
        steps.append(
            {
                "id": "first_comparison",
                "title": "Compare your major with one you're considering",
                "detail": (
                    "See the credits, semesters, cost, and earnings difference side by "
                    "side, then save it to your notebook."
                ),
                "reason": "No saved comparisons yet.",
                "action": {"label": "Start a comparison", "href": "/compare?from=record"},
            }
        )

    # Every saved option whose transfer figure is the student's own estimate
    # and that has no What-If on record: the single most useful thing to
    # bring to an advisor.
    estimated: dict[str, str] = {}
    for scenario in saved:
        for option in scenario.inputs.get("options", []):
            key = option["major"]
            if option.get("credits_transferable") is None:
                continue
            if option.get("provenance") == P.STUDENT_REPORTED and (
                (F.APPLICABLE_CREDITS, key) not in by_key
            ):
                estimated[key] = _major_display(key, majors) or key
    for key, display in sorted(estimated.items(), key=lambda kv: kv[1]):
        steps.append(
            {
                "id": f"what_if_{key}",
                "title": f"Run a What-If audit for {display}",
                "detail": (
                    f"Your saved comparison uses your own estimate of how many hours "
                    f"apply to {display}. A What-If audit shows the real figure, and "
                    "it's a good thing to ask your advisor to walk through with you."
                ),
                "reason": f"Transfer credits for {display} are an estimate.",
                "action": {"label": "Add a What-If audit", "href": "/compare?panel=audit"},
            }
        )

    decided = next((s for s in saved if s.decision), None)
    if saved and decided is None:
        steps.append(
            {
                "id": "record_plan",
                "title": "Note which way you're leaning",
                "detail": (
                    "Marking a plan on a saved comparison keeps your decision in your "
                    "notebook, so you can see how it changes over time."
                ),
                "reason": "You've saved comparisons but haven't marked a plan.",
                "action": {"label": "Review saved comparisons", "href": "/#comparisons"},
            }
        )

    if (F.GPA, "") not in by_key:
        steps.append(
            {
                "id": "add_gpa",
                "title": "Add your GPA",
                "detail": (
                    "Fork doesn't read GPA from your audit yet. Adding it keeps your "
                    "snapshot complete; it's labelled as your own figure."
                ),
                "reason": "No GPA in your record.",
                "action": {"label": "Update your details", "href": "/#record-details"},
                "optional": True,
            }
        )

    return steps


def serialize_event(event) -> dict:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "summary": event.summary,
        "detail": event.detail or {},
        "document_id": event.document_id,
        "scenario_id": event.scenario_id,
        "occurred_at": F._iso(event.occurred_at),
    }


def build_dashboard(db: Session, student: Student, reference_data: dict) -> dict:
    from accounts.routes import serialize_student

    facts = F.get_facts(db, student.id)
    documents = D.list_documents(db, student.id)
    saved = S.list_for(db, student.id)
    events = timeline.list_events(db, student.id, limit=50)

    return {
        "student": serialize_student(student),
        "snapshot": build_snapshot(student, facts, reference_data),
        "documents": [D.serialize_document(d, facts) for d in documents],
        "scenarios": [S.serialize(s) for s in saved],
        "timeline": [serialize_event(e) for e in events],
        "next_steps": build_next_steps(student.id, facts, documents, saved, reference_data),
        "storage": storage_status(),
        "provenance_labels": P.LABELS,
        "has_record": bool(facts or documents or saved),
    }
