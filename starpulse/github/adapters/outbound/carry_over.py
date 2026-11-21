"""Copy an old inbox database's rows into the store the inbox now lives in.

The old file is only read: it stays where it is, so a release that must roll back still finds its inbox."""

from pathlib import Path

from sqlalchemy import Table, create_engine, inspect, select, text
from sqlalchemy.engine import Engine

from starpulse.github.adapters.outbound.cursors import github_reconcile_state
from starpulse.github.adapters.outbound.inbox import INSERTS, github_inbox
from starpulse.github.adapters.outbound.queue import github_inbox_state

__all__ = ["carry_over"]

#: Rows in one transaction of the copy a store that cannot attach the file takes, so a large inbox is never held in memory whole.
_CHUNK = 500
#: Each table with the columns that identify a row in it, in the order the copy reads it.
_TABLES: tuple[tuple[Table, tuple[str, ...]], ...] = (
    (github_inbox, ("id",)),
    (github_inbox_state, ("delivery_id", "consumer")),
    (github_reconcile_state, ("name",)),
)


def carry_over(engine: Engine, source: Path) -> dict[str, int]:
    """Insert the rows of the inbox database at `source` that `engine`'s store lacks, and count the rows each table
    gained. A row the store holds is left as it is; a table `source` lacks, or no file, copies nothing."""
    if not source.is_file():
        return {}
    if engine.dialect.name == "sqlite":
        return _copy_attached(engine, source)
    return _copy_chunked(engine, source)


def _copy_attached(engine: Engine, source: Path) -> dict[str, int]:
    """One `INSERT ... SELECT` per table inside the store's own connection, so no row crosses into Python."""
    gained: dict[str, int] = {}
    with engine.connect() as db:
        db.execute(text("ATTACH DATABASE :source AS old"), {"source": str(source)})
        try:
            held = {name for (name,) in db.execute(text("SELECT name FROM old.sqlite_master WHERE type = 'table'"))}
            for table, key in _TABLES:
                if table.name not in held:
                    continue
                columns = ", ".join(c.name for c in table.columns if c.name != "id")
                result = db.execute(
                    text(
                        f"INSERT OR IGNORE INTO {table.name} ({columns}) "  # noqa: S608 - names from this module's own tables
                        f"SELECT {columns} FROM old.{table.name} ORDER BY {', '.join(key)}"
                    )
                )
                gained[table.name] = result.rowcount
            db.commit()
        finally:
            db.rollback()
            db.execute(text("DETACH DATABASE old"))
    return gained


def _copy_chunked(engine: Engine, source: Path) -> dict[str, int]:
    old = create_engine(f"sqlite:///{source}")
    gained: dict[str, int] = {}
    try:
        held = set(inspect(old).get_table_names())
        insert = INSERTS[engine.dialect.name]
        for table, key in _TABLES:
            if table.name not in held:
                continue
            gained[table.name] = 0
            columns = [c for c in table.columns if c.name != "id"]
            with old.connect() as reading:
                rows = reading.execute(select(*columns).order_by(*(table.c[k] for k in key))).mappings()
                while chunk := rows.fetchmany(_CHUNK):
                    with engine.begin() as db:
                        result = db.execute(insert(table).on_conflict_do_nothing(), [dict(row) for row in chunk])
                    gained[table.name] += result.rowcount
    finally:
        old.dispose()
    return gained
