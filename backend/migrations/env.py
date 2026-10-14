"""Alembic environment. Uses the same DATABASE_URL the app does."""

import sys
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.config import database_url, normalize_database_url  # noqa: E402
from db.models import Base  # noqa: E402
from sqlalchemy import create_engine, pool  # noqa: E402

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # A URL set programmatically (tests) wins over the environment.
    configured = config.get_main_option("sqlalchemy.url")
    return normalize_database_url(configured) if configured else database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:
        _run(connectable)
        return

    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        _run(connection)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite can't ALTER most things in place; batch mode lets future
        # migrations work on the local dev database too.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
