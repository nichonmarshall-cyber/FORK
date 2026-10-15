"""
The notebook schema.

Every table below hangs off `students` with ON DELETE CASCADE. Deleting an
account is a single row delete that takes the whole academic record with it,
which is the retention policy: Fork keeps a student's record until they
delete it, and deleting it actually removes it.

Kept deliberately small. Fork persists what the command center needs --
profile facts, document metadata and the facts read from them, saved
comparisons, and the timeline -- not raw grade histories. A confirmed degree
audit is stored as a summary of what Fork used from it, not as the full
parsed course list.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import false
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Student(Base):
    __tablename__ = "students"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    institution_id: Mapped[str] = mapped_column(String(32), default="unt")
    #: The shared, read-only demo notebook. Its record is fictional and is
    #: rebuilt by notebook/demo.py; no request may change it.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    auth_sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="student", cascade="all, delete-orphan", passive_deletes=True
    )


class AuthSession(Base):
    """A signed-in browser. Only a hash of the token is stored, so a copy of
    this table can't be replayed as a set of live logins."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    student_id: Mapped[str] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    student: Mapped[Student] = relationship(back_populates="auth_sessions")


class AcademicDocument(Base):
    """A document in the student's record, and what Fork took from it.

    `source` says how it got here: parsed and confirmed through Fork's audit
    review, or recorded by the student as metadata Fork has not read.
    `storage_status` says separately whether the raw file is held anywhere.
    Neither implies the other.
    """

    __tablename__ = "academic_documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    student_id: Mapped[str] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    doc_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))
    institution_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    program: Mapped[str | None] = mapped_column(String(200), nullable=True)
    program_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    catalog_year: Mapped[str | None] = mapped_column(String(32), nullable=True)
    document_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_status: Mapped[str] = mapped_column(String(16), default="not_stored")
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AcademicFact(Base):
    """One fact about the student, with where it came from.

    `scope` qualifies facts that only hold for one program -- applicable
    credits from a What-If audit belong to that major and no other. Empty for
    facts about the student as a whole.

    A fact backed by a document is deleted with that document. A figure whose
    evidence is gone is not still a confirmed figure.
    """

    __tablename__ = "academic_facts"
    __table_args__ = (UniqueConstraint("student_id", "key", "scope", name="uq_fact_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    student_id: Mapped[str] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(64), default="")
    value: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[str] = mapped_column(String(24))
    source_label: Mapped[str] = mapped_column(String(255))
    source_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("academic_documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SavedScenario(Base):
    """A comparison the student chose to keep.

    `inputs` is what was compared, with the provenance Fork could stand
    behind for each figure. `outcome` is the deterministic engine's result
    for those inputs, recomputed server-side when saved -- never a result a
    client posted.
    """

    __tablename__ = "saved_scenarios"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    student_id: Mapped[str] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(48), default="change_major_comparison")
    current_major: Mapped[str] = mapped_column(String(64))
    inputs: Mapped[dict] = mapped_column(JSON)
    outcome: Mapped[dict] = mapped_column(JSON)
    decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TimelineEvent(Base):
    """Something meaningful that happened to the student's record.

    Written by the service functions that make the change, never by a page
    view. Links to a document or scenario survive as plain history when the
    linked item is removed -- the event still happened.
    """

    __tablename__ = "timeline_events"
    __table_args__ = (Index("ix_timeline_student_time", "student_id", "occurred_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    student_id: Mapped[str] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(48))
    summary: Mapped[str] = mapped_column(String(300))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("academic_documents.id", ondelete="SET NULL"), nullable=True
    )
    scenario_id: Mapped[str | None] = mapped_column(
        ForeignKey("saved_scenarios.id", ondelete="SET NULL"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
