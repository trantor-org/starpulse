"""Versions a store's schema by the Alembic chain in `migrations/`.

A SQLite store is opened by many owners (the log, the history, the pulls and insights readers, each in its own thread
or process), so the chain runs under SQLite's write lock: the first opener builds the schema and the rest find it done.
"""

from __future__ import annotations

import threading
from functools import cache
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, inspect, text

from starpulse._internal.eventlog.tables import VERSION_TABLE, events

__all__ = ["alembic_config", "migrate"]

_MIGRATIONS = Path(__file__).parent / "migrations"
#: The revision whose schema a store has when it holds the tables but no version table: the release before the chain
#: upgraded each store to it on open, so a store last opened by that release is stamped here and upgraded from there.
_UNVERSIONED = "0019"
#: Alembic's environment is process-global, so two threads of one process cannot run the chain at once.
_RUNNING = threading.Lock()


def alembic_config(db: Connection) -> AlembicConfig:
    """The chain's configuration; its environment runs on `db`."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(_MIGRATIONS))
    config.attributes["connection"] = db
    return config


@cache
def _head() -> str | None:
    return ScriptDirectory(str(_MIGRATIONS)).get_current_head()


def _recorded(db: Connection) -> str | None:
    if not inspect(db).has_table(VERSION_TABLE):
        return None
    return db.execute(text(f"SELECT version_num FROM {VERSION_TABLE}")).scalar()


def migrate(engine: Engine) -> None:
    """Bring the SQLite store `engine` opens to the chain's head, building it, or stamping one from before the chain."""
    with _RUNNING, engine.connect() as db:
        if _recorded(db) == _head():
            return
        db.exec_driver_sql("BEGIN IMMEDIATE")  # the chain's DDL runs inside it, and a second opener waits here
        recorded = _recorded(db)
        config = alembic_config(db)
        if recorded is None and inspect(db).has_table(events.name):
            command.stamp(config, _UNVERSIONED)
        command.upgrade(config, "head")
        db.commit()
