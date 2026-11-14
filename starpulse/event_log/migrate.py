"""Versions a store's schema by the Alembic chain in `migrations/`.

Migrations are expand/contract: a release's migrations only add, and a migration that drops or renames sets
`CONTRACT = True`. The store records a reader floor, the latest contract revision at or below its own, so a release
whose chain holds the floor opens a store a newer release migrated.

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
from sqlalchemy import Connection, Engine, create_engine, delete, insert, inspect, select, text

from starpulse.event_log.tables import VERSION_TABLE, reader_floor

__all__ = [
    "StoreNotMigrated",
    "alembic_config",
    "chain_floor",
    "migrate",
    "migrate_chain",
    "record_floor",
    "require_migrated",
    "store_state",
    "stored_floor",
]

_MIGRATIONS = Path(__file__).parent / "migrations"
#: Alembic's environment is process-global, so two threads of one process cannot run the chain at once.
_RUNNING = threading.Lock()


class StoreNotMigrated(RuntimeError):
    """The store is not at the schema revision the chain declares; `starpulse migrate` brings it there."""


def alembic_config(db: Connection, migrations: Path = _MIGRATIONS) -> AlembicConfig:
    """The configuration of the chain in `migrations` (the event log's by default); its environment runs on `db`."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(migrations))
    config.attributes["connection"] = db
    return config


@cache
def _head(migrations: Path = _MIGRATIONS) -> str | None:
    return ScriptDirectory(str(migrations)).get_current_head()


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


@cache
def _revisions(migrations: Path = _MIGRATIONS) -> frozenset[str]:
    return frozenset(rev.revision for rev in ScriptDirectory(str(migrations)).walk_revisions())


def chain_floor(migrations: Path = _MIGRATIONS, at: str = "head") -> str:
    """The oldest revision that can read a store at `at`: the latest contract step at or below it, else the chain's base."""
    revisions = list(ScriptDirectory(str(migrations)).iterate_revisions(at, "base"))
    return next((rev for rev in revisions if getattr(rev.module, "CONTRACT", False)), revisions[-1]).revision


def stored_floor(db: Connection) -> str | None:
    """The reader floor the store records, or None for a store no release has recorded one in."""
    if not inspect(db).has_table(reader_floor.name):
        return None
    return db.execute(select(reader_floor.c.revision)).scalar()


def store_state(engine: Engine) -> dict[str, str | None]:
    """The revision and the reader floor the store `engine` opens records; it changes nothing."""
    with engine.connect() as db:
        return {"revision": _recorded(db), "floor": stored_floor(db)}


def record_floor(db: Connection, migrations: Path = _MIGRATIONS) -> None:
    """Record the floor of the store's revision, creating the table beside the revision table; the chain's environment runs it."""
    revision = _recorded(db)
    if revision is None:
        return
    reader_floor.create(db, checkfirst=True)
    floor = chain_floor(migrations, revision)
    if stored_floor(db) != floor:
        db.execute(delete(reader_floor))
        db.execute(insert(reader_floor).values(revision=floor))


def _ahead(recorded: str | None) -> bool:
    return recorded is not None and recorded not in _revisions()


def _opens(db: Connection, recorded: str | None) -> bool:
    """A store this chain reads as it is: at its head, or ahead of it with a floor the chain holds."""
    return recorded == _head() or (_ahead(recorded) and stored_floor(db) in _revisions())


def _settled(db: Connection) -> bool:
    """Whether `migrate` has nothing to do: an ahead store this chain opens, or one at the head with its floor recorded."""
    recorded = _recorded(db)
    if _ahead(recorded):
        return _opens(db, recorded)
    return recorded == _head() and stored_floor(db) == chain_floor()


def _refusal(engine: Engine, db: Connection, recorded: str | None) -> StoreNotMigrated:
    url = engine.url.render_as_string(hide_password=True)
    if not _ahead(recorded):
        return StoreNotMigrated(f"{url} is not migrated: run `starpulse migrate`")
    floor = stored_floor(db)
    named = f"reader floor {floor}" if floor else "no recorded reader floor"
    return StoreNotMigrated(f"{url} is at revision {recorded}, which this release lacks, and its {named} is not in the chain")


def _recorded(db: Connection, version_table: str = VERSION_TABLE) -> str | None:
    if not inspect(db).has_table(version_table):
        return None
    return db.execute(text(f"SELECT version_num FROM {version_table}")).scalar()


def migrate(engine: Engine) -> None:
    """Bring the SQLite store `engine` opens to the chain's head, building it."""
    with _RUNNING, engine.connect() as db:
        if _settled(db):
            return
        db.exec_driver_sql("BEGIN IMMEDIATE")  # the chain's DDL runs inside it, and a second opener waits here
        recorded = _recorded(db)
        if _ahead(recorded):
            raise _refusal(engine, db, recorded)
        if recorded is None and not inspect(db).get_table_names():
            _replay(db)
            db.commit()
            return
        config = alembic_config(db)
        command.upgrade(config, "head")
        db.commit()


def migrate_chain(engine: Engine, migrations: Path, version_table: str) -> None:
    """Bring the store `engine` opens to the head of another chain, `migrations` versioned in `version_table`.

    It runs under the lock every chain in the process shares, as Alembic's environment is process-global."""
    head = _head(migrations)
    with _RUNNING, engine.connect() as db:
        if _recorded(db, version_table) == head:
            return
        if engine.dialect.name == "sqlite":
            db.exec_driver_sql("BEGIN IMMEDIATE")
        command.upgrade(alembic_config(db, migrations), "head")
        db.commit()


def require_migrated(engine: Engine) -> None:
    """Raise `StoreNotMigrated` unless the store `engine` opens is at the chain's head; it changes nothing."""
    with engine.connect() as db:
        recorded = _recorded(db)
        if not _opens(db, recorded):
            raise _refusal(engine, db, recorded)

