"""The `github_reconcile_state` table and the `SqlCursors` that keep the reconcile pass's cursors and ETags in it."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, String, Table, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Engine

from starpulse.github.adapters.outbound.inbox import metadata

__all__ = ["Cursor", "SqlCursors", "github_reconcile_state"]

github_reconcile_state = Table(
    "github_reconcile_state",
    metadata,
    Column("name", String, primary_key=True),
    Column("cursor", String, nullable=False),
    Column("etag", String, nullable=True),
)
_INSERTS = {"sqlite": sqlite.insert, "postgresql": postgresql.insert}


@dataclass(frozen=True)
class Cursor:
    """How far a read has got: an ISO timestamp, and the ETag of the first page that read it."""

    value: str
    etag: str | None = None


class SqlCursors:
    """One `Cursor` for each name: `deliveries`, and `pulls:<repository>` for each repository."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._insert = _INSERTS[engine.dialect.name]

    def get(self, name: str) -> Cursor | None:
        with self._engine.connect() as db:
            row = db.execute(select(github_reconcile_state).where(github_reconcile_state.c.name == name)).one_or_none()
        return None if row is None else Cursor(row.cursor, row.etag)

    def put(self, name: str, cursor: Cursor) -> None:
        values = {"cursor": cursor.value, "etag": cursor.etag}
        statement = self._insert(github_reconcile_state).values(name=name, **values)
        with self._engine.begin() as db:
            db.execute(statement.on_conflict_do_update(index_elements=["name"], set_=values))
