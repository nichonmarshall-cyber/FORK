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
