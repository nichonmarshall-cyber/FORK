"""
Saved comparisons: what a student explored, and what they decided.

Two rules carry over from the rest of Fork:

  * The outcome is recomputed here by the deterministic engine from the
    submitted inputs. A client never posts a result for the notebook to
    store.

  * A figure is labelled by the evidence Fork can point to, not by the label
    the client attached. A transfer figure marked "UNT What-If Audit" is only
    recorded as What-If data if a confirmed What-If for that same program, in
    the student's record or their current audit session, says that same
    number. Otherwise it is kept as the student's own figure, with a note
    saying why. The existing calculate endpoint takes source strings on
    trust; the notebook is a record, so it doesn't.
"""

from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import SavedScenario

from . import facts as F
from . import provenance as P
from . import timeline

KIND = "change_major_comparison"


class ScenarioError(ValueError):
    def __init__(self, message: str, status_code: int = 400, detail: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


# --- provenance checks --------------------------------------------------


def _session_completed_evidence(audit_session) -> tuple[int, int, str] | None:
    if audit_session is None or not audit_session.has_confirmed_record:
        return None
    record = audit_session.uploaded_record
    return (
        round(record.completed_hours),
        round(record.in_progress_hours),
        record.audit_prepared_at or "Not stated",
    )


def _session_option_evidence(audit_session, majors: dict) -> tuple[str, int, str, str] | None:
    if audit_session is None:
        return None
    stored = audit_session.what_if_document
    if stored is None or not stored.is_confirmed:
        return None
    from documents.resolution import classify_document, resolve_comparison_inputs

    classification = classify_document(stored.record, majors)
    current = audit_session.uploaded_record if audit_session.has_confirmed_record else None
    resolved = resolve_comparison_inputs(
        current,
        stored.record,
        classification,
        audit_session.manual_transferable_by_major,
        acknowledged=audit_session.is_acknowledged(majors),
    )
    oc = resolved.option_credits
    if oc is None:
        return None
    return oc.program_key, oc.credits_transferable, oc.source, oc.source_date


def check_completed_provenance(
    db: Session,
    student_id: str,
    credits_completed: int,
    credits_in_progress: int,
    claimed_source: str,
    audit_session,
) -> dict:
    claims_document = claimed_source == P.CONFIRMED_AUDIT_SOURCE

    if claims_document:
        completed = F.get_fact(db, student_id, F.CREDITS_COMPLETED)
        in_progress = F.get_fact(db, student_id, F.CREDITS_IN_PROGRESS)
        if (
            completed is not None
            and completed.provenance == P.CONFIRMED_DOCUMENT
            and completed.value.get("value") == credits_completed
            and (in_progress.value.get("value") if in_progress else 0) == credits_in_progress
        ):
            return {
                "provenance": P.CONFIRMED_DOCUMENT,
                "source_label": completed.source_label,
                "source_date": completed.source_date,
                "document_id": completed.document_id,
            }
        evidence = _session_completed_evidence(audit_session)
        if evidence and evidence[0] == credits_completed and evidence[1] == credits_in_progress:
            return {
                "provenance": P.CONFIRMED_DOCUMENT,
                "source_label": P.CONFIRMED_AUDIT_SOURCE,
                "source_date": evidence[2],
                "document_id": None,
                "note": "From the audit you confirmed in this visit. Add it to your "
                "record to keep it with this comparison.",
            }
        return {
            "provenance": P.STUDENT_REPORTED,
            "source_label": P.STUDENT_SOURCE,
            "source_date": None,
            "document_id": None,
            "note": "Marked as coming from your degree audit, but it doesn't match a "
            "confirmed audit Fork has, so it's kept as your own figure.",
        }

    return {
        "provenance": P.STUDENT_REPORTED,
        "source_label": P.STUDENT_SOURCE,
        "source_date": None,
        "document_id": None,
    }


def check_option_provenance(
    db: Session,
    student_id: str,
    major_key: str,
    credits_transferable: int | None,
    claimed_source: str,
    audit_session,
    majors: dict,
) -> dict:
    if credits_transferable is None:
        return {"provenance": None, "source_label": None, "source_date": None, "document_id": None}

    if claimed_source.startswith(P.WHAT_IF_SOURCE_PREFIX):
        fact = F.get_fact(db, student_id, F.APPLICABLE_CREDITS, major_key)
        if fact is not None and fact.value.get("value") == credits_transferable:
            return {
                "provenance": P.WHAT_IF,
                "source_label": fact.source_label,
                "source_date": fact.source_date,
                "document_id": fact.document_id,
            }
        evidence = _session_option_evidence(audit_session, majors)
        if evidence and evidence[0] == major_key and evidence[1] == credits_transferable:
            return {
                "provenance": P.WHAT_IF,
                "source_label": evidence[2],
                "source_date": evidence[3],
                "document_id": None,
                "note": "From the What-If audit you confirmed in this visit. Add it to "
                "your record to keep it with this comparison.",
            }
        return {
            "provenance": P.STUDENT_REPORTED,
            "source_label": P.STUDENT_SOURCE,
            "source_date": None,
            "document_id": None,
            "note": "Marked as coming from a What-If audit, but it doesn't match a "
            "confirmed What-If for this program, so it's kept as your own estimate.",
        }

    return {
        "provenance": P.STUDENT_REPORTED,
        "source_label": P.STUDENT_SOURCE,
        "source_date": None,
        "document_id": None,
    }


# --- calculation --------------------------------------------------------

_LINE_ITEM_KEYS = (
    ("credits", "credits_lost"),
    ("credits", "credits_transferable"),
    ("credits", "credits_required_prospective"),
    ("timeline", "semesters_remaining_current"),
    ("timeline", "semesters_remaining_prospective"),
    ("timeline", "incremental_semesters"),
    ("financial", "incremental_tuition"),
    ("financial", "foregone_earnings_cost"),
    ("financial", "incremental_total_cost"),
    ("earnings", "median_salary_current"),
    ("earnings", "median_salary_prospective"),
    ("earnings", "annual_salary_delta"),
)


def _compact_outcome(snapshot) -> dict:
    options = []
    for outcome in snapshot.outcomes:
        entry = {
            "major_key": outcome.major_key,
            "major": outcome.major_display,
            "status": outcome.status,
        }
        if outcome.detail is not None:
            entry["summary"] = outcome.detail["summary"]
        if outcome.dimensions is not None:
            entry["line_items"] = {
                key: outcome.dimensions[block][key]
                for block, key in _LINE_ITEM_KEYS
                if key in outcome.dimensions.get(block, {})
            }
        if outcome.missing_fields:
            entry["missing_fields"] = outcome.missing_fields
        if outcome.error:
            entry["error"] = outcome.error
        options.append(entry)
    return {
        "anchor": {"major_key": snapshot.anchor_key, "major": snapshot.anchor_display},
        "credits_completed": snapshot.credits_completed,
        "options": options,
        "assumptions": snapshot.assumptions,
        "limitations": snapshot.limitations,
    }


def calculate(inputs: dict, reference_data: dict) -> dict:
    """Run the engine on stored inputs. Pure: no database, no session."""
    from decision_paths.change_major.comparison import run_multi_comparison
    from decision_paths.change_major.comparison_inputs import (
        ComparisonOption,
        MultiComparisonInputs,
    )

    completed = inputs["credits_completed"]
    try:
        multi = MultiComparisonInputs(
            current_major=inputs["current_major"],
            credits_completed=completed["value"],
            credits_in_progress=inputs["credits_in_progress"],
            credits_source=completed["source_label"],
            credits_source_date=completed.get("source_date") or "Not stated",
            options=[
                ComparisonOption(
                    major=o["major"],
                    credits_transferable=o["credits_transferable"],
                    credits_transferable_source=o.get("source_label") or P.STUDENT_SOURCE,
                )
                for o in inputs["options"]
            ],
        )
    except ValidationError as e:
        first = e.errors()[0] if e.errors() else {}
        original = first.get("ctx", {}).get("error")
        message = str(original) if original is not None else first.get("msg", "Invalid inputs.")
        raise ScenarioError(message.removeprefix("Value error, "), 422)
    except ValueError as e:
        raise ScenarioError(str(e), 422)

    try:
        snapshot = run_multi_comparison(multi, reference_data)
    except ValueError as e:
        raise ScenarioError(str(e), 400)
    return _compact_outcome(snapshot)


def build_inputs(
    db: Session,
    student_id: str,
    *,
    current_major: str,
    credits_completed: int,
    credits_in_progress: int,
    credits_source: str,
    options: list[dict],
    audit_session,
    majors: dict,
) -> dict:
    completed = check_completed_provenance(
        db, student_id, credits_completed, credits_in_progress, credits_source, audit_session
    )
    completed["value"] = credits_completed
    built_options = []
    for option in options:
        checked = check_option_provenance(
            db,
            student_id,
            option["major"],
            option.get("credits_transferable"),
            option.get("credits_transferable_source") or P.STUDENT_SOURCE,
            audit_session,
            majors,
        )
        built_options.append(
            {
                "major": option["major"],
                "credits_transferable": option.get("credits_transferable"),
                **checked,
            }
        )
    return {
        "current_major": current_major,
        "credits_completed": completed,
        "credits_in_progress": credits_in_progress,
        "options": built_options,
    }


def default_title(outcome: dict) -> str:
    anchor = outcome["anchor"]["major"]
    names = [o["major"] for o in outcome["options"]]
    if not names:
        return f"Reviewed {anchor}"
    if len(names) == 1:
        joined = names[0]
    else:
        joined = ", ".join(names[:-1]) + f" and {names[-1]}"
    return f"Compared {anchor} with {joined}"[:200]


def save(
    db: Session,
    student_id: str,
    inputs: dict,
    outcome: dict,
    title: str | None,
    note: str | None,
) -> SavedScenario:
    now = datetime.now(timezone.utc)
    scenario = SavedScenario(
        student_id=student_id,
        title=(title or "").strip()[:200] or default_title(outcome),
        kind=KIND,
        current_major=inputs["current_major"],
        inputs=inputs,
        outcome=outcome,
        note=(note or "").strip()[:2000] or None,
        calculated_at=now,
    )
    db.add(scenario)
    db.flush()
    timeline.record_event(
        db,
        student_id,
        timeline.COMPARISON_SAVED,
        f"Saved a comparison: {scenario.title}.",
        detail={
            "options": [o["major_key"] for o in outcome["options"]],
            "input_provenance": _provenance_digest(inputs),
        },
        scenario_id=scenario.id,
    )
    return scenario


def _provenance_digest(inputs: dict) -> dict:
    return {
        "credits_completed": inputs["credits_completed"]["provenance"],
        "options": {o["major"]: o.get("provenance") for o in inputs["options"]},
    }


def refresh(
    db: Session, student_id: str, scenario: SavedScenario, reference_data: dict
) -> bool:
    """Re-check provenance against the record as it stands, and recalculate.

    Provenance is re-derived from the record because the evidence can change
    under a saved comparison: if the audit behind its credits has since been
    removed, the figure is no longer document-backed and must stop saying so.
    Returns True when anything a student would see changed.
    """
    majors = reference_data["majors"]
    old = scenario.inputs
    rebuilt = build_inputs(
        db,
        student_id,
        current_major=old["current_major"],
        credits_completed=old["credits_completed"]["value"],
        credits_in_progress=old["credits_in_progress"],
        credits_source=old["credits_completed"]["source_label"],
        options=[
            {
                "major": o["major"],
                "credits_transferable": o.get("credits_transferable"),
                "credits_transferable_source": o.get("source_label") or P.STUDENT_SOURCE,
            }
            for o in old["options"]
        ],
        audit_session=None,
        majors=majors,
    )
    outcome = calculate(rebuilt, reference_data)
    changed = outcome != scenario.outcome or _provenance_digest(rebuilt) != _provenance_digest(old)

    if not changed:
        return False

    scenario.inputs = rebuilt
    scenario.outcome = outcome
    scenario.calculated_at = datetime.now(timezone.utc)
    timeline.record_event(
        db,
        student_id,
        timeline.COMPARISON_UPDATED,
        f"Updated a saved comparison with your current record: {scenario.title}.",
        detail={"input_provenance": _provenance_digest(rebuilt)},
        scenario_id=scenario.id,
    )
    return True


def set_decision(
    db: Session, student_id: str, scenario: SavedScenario, decision: str | None
) -> None:
    """Record which path the student says they're taking, or clear it.

    One plan at a time across the notebook: choosing one clears any other,
    because a record that says a student plans both to stay and to switch
    describes nobody.
    """
    outcome = scenario.outcome
    anchor = outcome["anchor"]
    names = {anchor["major_key"]: anchor["major"]}
    names.update({o["major_key"]: o["major"] for o in outcome["options"]})

    if decision is not None and decision not in names:
        raise ScenarioError("Choose your current major or one of the options in this comparison.")
    if decision == scenario.decision:
        return

    if decision is None:
        scenario.decision = None
        timeline.record_event(
            db,
            student_id,
            timeline.PLAN_CLEARED,
            f"Cleared your plan from {scenario.title}.",
            scenario_id=scenario.id,
        )
        return

    for other in db.scalars(
        select(SavedScenario).where(
            SavedScenario.student_id == student_id,
            SavedScenario.id != scenario.id,
            SavedScenario.decision.is_not(None),
        )
    ):
        other.decision = None

    scenario.decision = decision
    if decision == anchor["major_key"]:
        text = f"Marked staying in {anchor['major']} as your current plan."
    else:
        text = f"Marked switching to {names[decision]} as your current plan."
    timeline.record_event(
        db,
        student_id,
        timeline.PLAN_CHOSEN,
        text,
        detail={"decision": decision, "stay": decision == anchor["major_key"]},
        scenario_id=scenario.id,
    )


def remove(db: Session, student_id: str, scenario: SavedScenario) -> None:
    title = scenario.title
    db.delete(scenario)
    db.flush()
    timeline.record_event(
        db,
        student_id,
        timeline.COMPARISON_REMOVED,
        f"Removed a saved comparison: {title}.",
    )


def list_for(db: Session, student_id: str) -> list[SavedScenario]:
    return list(
        db.scalars(
            select(SavedScenario)
            .where(SavedScenario.student_id == student_id)
            .order_by(SavedScenario.created_at.desc())
        )
    )


def get_owned(db: Session, student_id: str, scenario_id: str) -> SavedScenario:
    scenario = db.get(SavedScenario, scenario_id)
    if scenario is None or scenario.student_id != student_id:
        raise ScenarioError("That comparison isn't in your notebook.", 404)
    return scenario


def serialize(scenario: SavedScenario) -> dict:
    inputs = scenario.inputs
    completed = dict(inputs["credits_completed"])
    completed["provenance_label"] = P.LABELS[completed["provenance"]]
    options = []
    for option in inputs["options"]:
        o = dict(option)
        o["provenance_label"] = P.LABELS[o["provenance"]] if o.get("provenance") else None
        options.append(o)
    return {
        "id": scenario.id,
        "title": scenario.title,
        "kind": scenario.kind,
        "current_major": scenario.current_major,
        "inputs": {
            "current_major": inputs["current_major"],
            "credits_completed": completed,
            "credits_in_progress": inputs["credits_in_progress"],
            "options": options,
        },
        "outcome": scenario.outcome,
        "outcome_provenance": P.DERIVED,
        "outcome_provenance_label": P.LABELS[P.DERIVED],
        "decision": scenario.decision,
        "note": scenario.note,
        "calculated_at": F._iso(scenario.calculated_at),
        "created_at": F._iso(scenario.created_at),
        "updated_at": F._iso(scenario.updated_at),
    }
