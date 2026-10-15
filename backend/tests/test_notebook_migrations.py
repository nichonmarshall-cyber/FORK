"""The Alembic migration builds exactly the schema the ORM expects.

If someone changes a model without writing a migration, this fails rather
than production finding out on deploy.
"""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from db.models import Base

BACKEND = Path(__file__).resolve().parent.parent


def _config(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_upgrade_matches_models_and_downgrade_is_clean(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    config = _config(url)
    command.upgrade(config, "head")

    engine = create_engine(url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []

    command.downgrade(config, "base")
    assert set(inspect(create_engine(url)).get_table_names()) <= {"alembic_version"}


def test_database_url_normalization():
    from db.config import normalize_database_url

    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("sqlite:///./x.db") == "sqlite:///./x.db"


def test_app_startup_creates_the_schema_so_sign_up_works(tmp_path, monkeypatch):
    """Regression: production came up healthy with no tables, and every
    sign-up failed with "no such table: students". Starting the app must
    bring the schema up to date by itself."""
    from fastapi.testclient import TestClient

    import main
    from accounts import rate_limit
    from db import config

    monkeypatch.setenv("FORK_COOKIE_SECURE", "false")
    monkeypatch.delenv("FORK_AUTO_MIGRATE", raising=False)
    config.configure(f"sqlite:///{tmp_path / 'fresh.db'}")
    rate_limit.reset_all()

    with TestClient(main.app) as client:  # runs the startup lifespan
        response = client.post(
            "/account/register",
            json={"email": "first@example.edu", "password": "a long password"},
            headers={"X-Fork-CSRF": "1"},
        )
        assert response.status_code == 201, response.text
        assert client.get("/notebook").status_code == 200

    # A second start against the same database is a no-op, not an error.
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200


def test_auto_migrate_can_be_turned_off(monkeypatch):
    from db.migrate import auto_migrate_enabled

    monkeypatch.setenv("FORK_AUTO_MIGRATE", "false")
    assert auto_migrate_enabled() is False
    monkeypatch.delenv("FORK_AUTO_MIGRATE")
    assert auto_migrate_enabled() is True
