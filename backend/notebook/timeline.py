"""
The academic journey: what happened to a student's record, in their words.

Events are written only by the service functions that make a meaningful
change -- a document added, a fact updated, a comparison saved, a plan
chosen. Nothing here is called from a read, so opening a page never adds a
line to someone's history.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import TimelineEvent

NOTEBOOK_STARTED = "notebook_started"
AUDIT_ADDED = "audit_added"
WHAT_IF_ADDED = "what_if_added"
DOCUMENT_RECORDED = "document_recorded"
DOCUMENT_FILE_ATTACHED = "document_file_attached"
DOCUMENT_REMOVED = "document_removed"
FACTS_UPDATED = "facts_updated"
COMPARISON_SAVED = "comparison_saved"
COMPARISON_UPDATED = "comparison_updated"
COMPARISON_REMOVED = "comparison_removed"
PLAN_CHOSEN = "plan_chosen"
PLAN_CLEARED = "plan_cleared"

EVENT_TYPES = frozenset(
    {
        NOTEBOOK_STARTED,
        AUDIT_ADDED,
        WHAT_IF_ADDED,
        DOCUMENT_RECORDED,
        DOCUMENT_FILE_ATTACHED,
        DOCUMENT_REMOVED,
        FACTS_UPDATED,
        COMPARISON_SAVED,
        COMPARISON_UPDATED,
        COMPARISON_REMOVED,
        PLAN_CHOSEN,
        PLAN_CLEARED,
    }
)


def record_event(
    db: Session,
    student_id: str,
    event_type: str,
    summary: str,
    *,
    detail: dict | None = None,
    document_id: str | None = None,
    scenario_id: str | None = None,
) -> TimelineEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown timeline event type '{event_type}'.")
    event = TimelineEvent(
        student_id=student_id,
        event_type=event_type,
        summary=summary[:300],
        detail=detail or {},
        document_id=document_id,
        scenario_id=scenario_id,
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event)
    return event


def list_events(
    db: Session, student_id: str, limit: int = 50, before: datetime | None = None
) -> list[TimelineEvent]:
    query = select(TimelineEvent).where(TimelineEvent.student_id == student_id)
    if before is not None:
        query = query.where(TimelineEvent.occurred_at < before)
    query = query.order_by(TimelineEvent.occurred_at.desc(), TimelineEvent.id.desc()).limit(limit)
    return list(db.scalars(query))
