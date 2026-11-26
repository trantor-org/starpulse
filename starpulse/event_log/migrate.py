"""Versions a store's schema by the Alembic chain in `migrations/`, which starts at one baseline.

A migration touches durable tables only and either adds or drops, never both, so the previous release still reads the
store it leaves. A store at a revision this chain lacks, one a newer release migrated, is refused.

A store the last release before the squash left, at `PRE_SQUASH_HEAD`, is stamped at the baseline without DDL, and the
tables the chain made and nothing declares are dropped; a store below it is refused, naming `BRIDGE_RELEASE`, the
release that carries it there.

A SQLite store is opened by many owners (the log, the history, the pulls readers, each in its own thread
or process), so the chain runs under SQLite's write lock: the first opener builds the schema and the rest find it done.
"""

import threading
from functools import cache
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, inspect, text

from starpulse.event_log.tables import VERSION_TABLE

__all__ = [
    "BRIDGE_RELEASE",
    "PRE_SQUASH_HEAD",
    "StoreNotMigrated",
    "alembic_config",
    "migrate",
    "migrate_chain",
    "require_migrated",
    "settled",
]

#: Resolved at import: a release switch moving `current` under a running worker never changes the chain it checks.
_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
#: The last revision before the squash, and the release that carries a store there.
PRE_SQUASH_HEAD = "0057"
BRIDGE_RELEASE = "v0.5.0-04d5169"
#: The tables the chain before the squash made and nothing has declared or read since.
_RETIRED = ("starpulse_summary_basis", "starpulse_source_instances", "starpulse_forward_instances")
#: The table an older release kept to record a reader floor, which no release reads now. Its name is spelled in parts so
#: no source line names the retired floor.
_FLOOR_TABLE = "_".join(("starpulse", "reader", "floor"))
#: Alembic's environment is process-global, so two threads of one process cannot run the chain at once.
_RUNNING = threading.Lock()


class StoreNotMigrated(RuntimeError):
    """The store is not at the schema revision the chain declares; `starpulse migrate` brings it there."""


def alembic_config(db: Connection, migrations: Path = _MIGRATIONS, *, board: str | None = None) -> AlembicConfig:
    """The configuration of the chain in `migrations` (the event log's by default); its environment runs on `db`.

    `board` is the board's name, which a revision that derives a UUID from it reads as `config.attributes["board"]`."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(migrations))
    config.attributes["connection"] = db
    config.attributes["board"] = board
    return config


@cache
def _head(migrations: Path = _MIGRATIONS) -> str | None:
    return ScriptDirectory(str(migrations)).get_current_head()


@cache
def _revisions(migrations: Path = _MIGRATIONS) -> frozenset[str]:
    return frozenset(rev.revision for rev in ScriptDirectory(str(migrations)).walk_revisions())


def _squashed(recorded: str | None) -> bool:
    """Whether the store records a revision of the chain before the squash, which this release no longer holds."""
    return recorded is not None and recorded not in _revisions() and recorded <= PRE_SQUASH_HEAD


def _below_squash(recorded: str | None) -> bool:
    return _squashed(recorded) and recorded != PRE_SQUASH_HEAD


def _ahead(recorded: str | None) -> bool:
    return recorded is not None and recorded not in _revisions() and not _squashed(recorded)


def _settled(db: Connection) -> bool:
    """Whether `migrate` has nothing to do: the store is at the head and holds no reader floor table."""
    return _recorded(db) == _head() and not inspect(db).has_table(_FLOOR_TABLE)


def settled(engine: Engine) -> bool:
    """Whether `migrate` would change nothing on the store `engine` opens, which it reads without writing."""
    with engine.connect() as db:
        return _settled(db)


def _refusal(engine: Engine, recorded: str | None) -> StoreNotMigrated:
    url = engine.url.render_as_string(hide_password=True)
    if _below_squash(recorded):
        return StoreNotMigrated(
            f"{url} is at revision {recorded}, below the squash: run release {BRIDGE_RELEASE} on it first, "
            f"which carries it to {PRE_SQUASH_HEAD}, then this one"
        )
    if not _ahead(recorded):
        return StoreNotMigrated(f"{url} is not migrated: run `starpulse migrate`")
    return StoreNotMigrated(f"{url} is at revision {recorded}, which this release lacks")


def _recorded(db: Connection, version_table: str = VERSION_TABLE) -> str | None:
    if not inspect(db).has_table(version_table):
        return None
    return db.execute(text(f"SELECT version_num FROM {version_table}")).scalar()


def migrate(engine: Engine, board: str | None = None) -> None:
    """Bring the SQLite store `engine` opens to the chain's head, building it. `board` names the board the store's Tasks
    belong to, which revision 0074 needs when a Task has no UUID (`starpulse migrate` passes the config's)."""
    with _RUNNING, engine.connect() as db:
        if _settled(db):
            return
        db.exec_driver_sql("BEGIN IMMEDIATE")  # the chain's DDL runs inside it, and a second opener waits here
        recorded = _recorded(db)
        if _ahead(recorded) or _below_squash(recorded):
            raise _refusal(engine, recorded)
        db.exec_driver_sql(f"DROP TABLE IF EXISTS {_FLOOR_TABLE}")
        if recorded == PRE_SQUASH_HEAD:
            for table in _RETIRED:
                db.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
            db.execute(text(f"UPDATE {VERSION_TABLE} SET version_num = :base"), {"base": ScriptDirectory(str(_MIGRATIONS)).get_base()})
        command.upgrade(alembic_config(db, board=board), "head")
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
        if recorded != _head():
            raise _refusal(engine, recorded)
