"""Student accounts and the academic notebook.

Revision ID: 0001_notebook
Revises:
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_notebook"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=True),
        sa.Column("institution_id", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_students_email", "students", ["email"], unique=True)

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "student_id",
            sa.String(32),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_student_id", "auth_sessions", ["student_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)

    op.create_table(
        "academic_documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "student_id",
            sa.String(32),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("doc_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("institution_id", sa.String(32), nullable=True),
        sa.Column("program", sa.String(200), nullable=True),
        sa.Column("program_key", sa.String(64), nullable=True),
        sa.Column("catalog_year", sa.String(32), nullable=True),
        sa.Column("document_date", sa.String(64), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("storage_status", sa.String(16), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("content_type", sa.String(100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_academic_documents_student_id", "academic_documents", ["student_id"])

    op.create_table(
        "academic_facts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "student_id",
            sa.String(32),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.String(24), nullable=False),
        sa.Column("source_label", sa.String(255), nullable=False),
        sa.Column("source_date", sa.String(64), nullable=True),
        sa.Column(
            "document_id",
            sa.String(32),
            sa.ForeignKey("academic_documents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "key", "scope", name="uq_fact_key"),
    )
    op.create_index("ix_academic_facts_student_id", "academic_facts", ["student_id"])
    op.create_index("ix_academic_facts_document_id", "academic_facts", ["document_id"])

    op.create_table(
        "saved_scenarios",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "student_id",
            sa.String(32),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("current_major", sa.String(64), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_saved_scenarios_student_id", "saved_scenarios", ["student_id"])

    op.create_table(
        "timeline_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "student_id",
            sa.String(32),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("summary", sa.String(300), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column(
            "document_id",
            sa.String(32),
            sa.ForeignKey("academic_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "scenario_id",
            sa.String(32),
            sa.ForeignKey("saved_scenarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_timeline_events_student_id", "timeline_events", ["student_id"])
    op.create_index(
        "ix_timeline_student_time", "timeline_events", ["student_id", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_table("timeline_events")
    op.drop_table("saved_scenarios")
    op.drop_table("academic_facts")
    op.drop_table("academic_documents")
    op.drop_table("auth_sessions")
    op.drop_table("students")
