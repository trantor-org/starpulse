"""Hub mode: the same package served from a Postgres history, started by `starpulse serve --hub`.

This module and what it imports (Alembic, the Postgres driver) are the hub extras (`pip install 'starpulse[hub]'`).
Only `serve --hub` imports it, so an IC instance on SQLite runs without them.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

__all__ = ["VERSION_TABLE", "HubError", "prepare"]

#: Where the database records the revision it is at, named so it never meets a host project's own Alembic table.
VERSION_TABLE = "starpulse_alembic_version"
_MIGRATIONS = Path(__file__).parent / "migrations"


class HubError(ValueError):
    """The config cannot run a hub; the message says what to change."""


def prepare(database_url: str | None) -> None:
    """Bring the hub's Postgres database to the latest schema; a config that names none is refused."""
    try:
        postgres = database_url is not None and make_url(database_url).get_backend_name() == "postgresql"
    except ArgumentError:
        postgres = False
    if not postgres or database_url is None:
        raise HubError("hub mode needs a Postgres database_url (postgresql+psycopg://...) in the config")
    _upgrade(database_url)


def _upgrade(url: str) -> None:
    """Run every revision the database has not yet seen, in one transaction (Postgres DDL rolls back)."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(_MIGRATIONS))
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    except SQLAlchemyError as exc:
        raise HubError(f"cannot bring the hub database to the latest schema: {exc.__class__.__name__}: {exc}") from exc
    finally:
        engine.dispose()
