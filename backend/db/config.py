"""
Database connection, configured by DATABASE_URL.

Production runs on Postgres. Local development and tests default to a SQLite
file so the app runs with no setup; nothing in the schema depends on a
Postgres-only feature.

Render (and most hosts) hand out URLs starting with ``postgres://`` or
``postgresql://``. SQLAlchemy needs the driver named, so both are rewritten to
``postgresql+psycopg://`` here rather than asking whoever deploys to know that.
"""

import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

DEFAULT_DATABASE_URL = "sqlite:///./fork_dev.db"


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def database_url() -> str:
    return normalize_database_url(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))


def _build_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # One shared connection, or every session would see its own
            # empty in-memory database.
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):
            # SQLite ignores ON DELETE CASCADE unless asked. Account deletion
            # relies on it, so it isn't optional here.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    return create_engine(url, pool_pre_ping=True)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        _engine = _build_engine(database_url())
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def configure(url: str) -> Engine:
    """Point the app at a specific database. Used by tests and migrations."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = _build_engine(normalize_database_url(url))
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
