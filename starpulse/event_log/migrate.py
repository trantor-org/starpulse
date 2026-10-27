"""Versions a store's schema by the Alembic chain in `migrations/`.

A SQLite store is opened by many owners (the log, the history, the pulls readers, each in its own thread
or process), so the chain runs under SQLite's write lock: the first opener builds the schema and the rest find it done.
A store with no tables replays a template the chain built once per process instead of running the chain again.
"""

from __future__ import annotations

import threading
from functools import cache
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, create_engine, inspect, text

from starpulse.event_log.tables import VERSION_TABLE, events

__all__ = ["StoreNotMigrated", "alembic_config", "migrate", "require_migrated"]

_MIGRATIONS = Path(__file__).parent / "migrations"
#: The revision whose schema a store has when it holds the tables but no version table: the release before the chain
#: upgraded each store to it on open, so a store last opened by that release is stamped here and upgraded from there.
_UNVERSIONED = "0019"
#: Alembic's environment is process-global, so two threads of one process cannot run the chain at once.
_RUNNING = threading.Lock()


class StoreNotMigrated(RuntimeError):
    """The store is not at the schema revision the chain declares; `starpulse migrate` brings it there."""


def alembic_config(db: Connection) -> AlembicConfig:
    """The chain's configuration; its environment runs on `db`."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(_MIGRATIONS))
    config.attributes["connection"] = db
    return config


@cache
def _head() -> str | None:
    return ScriptDirectory(str(_MIGRATIONS)).get_current_head()


@cache
def _template() -> tuple[tuple[str, ...], dict[str, list[tuple]]]:
    """The DDL of a store the chain built, in the order SQLite created it, and the rows each table holds."""
    engine = create_engine("sqlite://")
    with engine.connect() as db:
        command.upgrade(alembic_config(db), "head")
        db.commit()
        ddl = (
            db.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
            )
            .scalars()
            .all()
        )
        tables = inspect(db).get_table_names()
        rows = {table: list(db.exec_driver_sql(f'SELECT * FROM "{table}"')) for table in tables}
        return tuple(ddl), {table: held for table, held in rows.items() if held}


def _replay(db: Connection) -> None:
    """Build the template's schema and rows on the empty store `db`; SQLite's backup API cannot write under its lock."""
    ddl, rows = _template()
    for statement in ddl:
        db.exec_driver_sql(statement)
    for table, held in rows.items():
        marks = ", ".join("?" * len(held[0]))
        db.exec_driver_sql(f'INSERT INTO "{table}" VALUES ({marks})', [tuple(row) for row in held])


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
        if recorded is None and not inspect(db).get_table_names():
            _replay(db)
            db.commit()
            return
        config = alembic_config(db)
        if recorded is None and inspect(db).has_table(events.name):
            command.stamp(config, _UNVERSIONED)
        command.upgrade(config, "head")
        db.commit()


def require_migrated(engine: Engine) -> None:
    """Raise `StoreNotMigrated` unless the store `engine` opens is at the chain's head; it changes nothing."""
    with engine.connect() as db:
        if _recorded(db) != _head():
            url = engine.url.render_as_string(hide_password=True)
            raise StoreNotMigrated(f"{url} is not migrated: run `starpulse migrate`")
