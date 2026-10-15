"""Flag the read-only demo account.

Revision ID: 0002_demo_flag
Revises: 0001_notebook
Create Date: 2026-10-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_demo_flag"
down_revision = "0001_notebook"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("students") as batch:
        batch.add_column(
            sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("students") as batch:
        batch.drop_column("is_demo")
