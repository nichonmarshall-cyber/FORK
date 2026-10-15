"""
Bring the database schema up to date when the app starts.

Account and notebook routes need their tables. Relying on the deploy's start
command to run `alembic upgrade head` meant a deployment that didn't was
up and healthy but failed every sign-up with "no such table: students".
Running the migrations here makes the schema part of starting the app.

Upgrading to head is idempotent: when the schema is already current it does
nothing. Set FORK_AUTO_MIGRATE=false to manage migrations by hand instead.
"""

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from .config import get_engine

logger = logging.getLogger("fork.db")

BACKEND = Path(__file__).resolve().parent.parent


def auto_migrate_enabled() -> bool:
    value = os.environ.get("FORK_AUTO_MIGRATE", "true").strip().lower()
    return value not in ("0", "false", "no", "off")


def upgrade_to_head() -> None:
    engine = get_engine()
    if engine.dialect.name == "sqlite" and os.environ.get("RENDER"):
        # Render's disk is replaced on every deploy, so a SQLite file there
        # loses every account each time. Say so loudly instead of silently.
        logger.warning(
            "DATABASE_URL is not set; using SQLite on Render's ephemeral disk. "
            "Accounts and notebooks will be lost on the next deploy. Set "
            "DATABASE_URL to a Postgres database."
        )

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    with engine.begin() as connection:
        # env.py uses this connection rather than opening its own, so the
        # migration runs against exactly the database the app will use.
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    logger.info("Database schema is up to date.")
