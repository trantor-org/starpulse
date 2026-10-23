"""The read model's reads: what the page, the agent CLI, search and the Scheduler ask of the Task tables."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, Select

from starpulse._internal.readmodel import queries, rows
from starpulse._internal.readmodel.declared import Declared
from starpulse._internal.readmodel.fold import Row


class ReadModel:
    def __init__(self, engine: Engine, declared: dict[str, Declared] | None = None) -> None:
        self._engine = engine
        self._declared = declared or {}

    def task(self, task_id: str) -> Row | None:
        """The Task's whole row, archived or not; None when it has none."""
        with self._engine.connect() as db:
            return rows.load(db, task_id)

    def snapshot(self, state: str | None = None) -> list[dict[str, Any]]:
        """The unarchived Tasks as summaries, in id order."""
        return self._summaries(queries.snapshot(state))

    def with_field(self, name: str, value: object) -> list[str]:
        """The ids of unarchived Tasks whose queried declared field `name` equals `value`; KeyError when not queried."""
        field = self._declared.get(name)
        if field is None or not field.queried:
            raise KeyError(name)
        return self._ids(queries.with_field(field.column, value))

    def ready(self, state: str, done: str) -> list[str]:
        """The ids of unarchived Tasks in `state` whose dependencies are all in `done`."""
        return self._ids(queries.ready(state, done))

    def since(self, seq: int, limit: int = 1000) -> list[dict[str, Any]]:
        """Summaries of the Tasks changed after `seq`, archived ones included, in the order they changed."""
        return self._summaries(queries.since(seq, limit))

    def _summaries(self, statement: Select[Any]) -> list[dict[str, Any]]:
        with self._engine.connect() as db:
            return [dict(item) for item in db.execute(statement).mappings()]

    def _ids(self, statement: Select[Any]) -> list[str]:
        with self._engine.connect() as db:
            return list(db.execute(statement).scalars())
