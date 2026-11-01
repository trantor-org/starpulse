"""The read model's reads: what the page, the agent CLI, search and the Scheduler ask of the Task tables."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, Select, func, select

from starpulse.event_log.readmodel import queries, rows
from starpulse.event_log.readmodel.declared import Declared
from starpulse.event_log.readmodel.fold import Row
from starpulse.event_log.readmodel.tables import machine_tasks


class ReadModel:
    def __init__(self, engine: Engine, declared: dict[str, Declared] | None = None) -> None:
        self._engine = engine
        self._declared = declared or {}

    def task(self, task_id: str) -> Row | None:
        """The Task's whole row, archived or not; None when it has none."""
        with self._engine.connect() as db:
            return rows.load(db, task_id)

    def snapshot(self, state: str | None = None) -> list[dict[str, Any]]:
        """The unarchived Tasks as summaries with their Acceptance Criteria, in id order."""
        summaries = self._summaries(queries.snapshot(state))
        by_task: dict[str, list[dict[str, Any]]] = {summary["id"]: [] for summary in summaries}
        for item in self._summaries(queries.live_criteria()):
            by_task.get(item.pop("task_id"), []).append(item)
        return [summary | {"criteria": by_task[summary["id"]]} for summary in summaries]

    def archived(self, before: float | None, limit: int) -> list[dict[str, Any]]:
        """Up to `limit` archived Tasks changed before `before` (None: any time), newest first."""
        return self._summaries(queries.archived(before, limit))

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

    def position(self) -> int:
        """The stream position of the newest change; 0 when no Task has one."""
        with self._engine.connect() as db:
            return db.execute(queries.position()).scalar() or 0

    def machine_tasks(self, machine: str, since: float | None = None) -> list[dict[str, Any]]:
        """Each agent `machine` holds that it placed at or after `since` (None: every one), as the page draws it."""
        return [agent for _, agent, _ in self._machine_rows(machine, since)]

    def machine_task(self, machine: str, task: str) -> dict[str, Any] | None:
        """The agent `machine` holds for `task`, or None when it places none."""
        statement = select(machine_tasks.c.agent).where(machine_tasks.c.machine == machine, machine_tasks.c.task == task)
        with self._engine.connect() as db:
            return db.execute(statement).scalar()

    def machine_lanes(self, since: float | None = None) -> dict[str, list[dict[str, Any]]]:
        """Every machine's agents placed at or after `since`, keyed by machine; a machine with none is absent."""
        lanes: dict[str, list[dict[str, Any]]] = {}
        for machine, agent, _ in self._machine_rows(None, since):
            lanes.setdefault(machine, []).append(agent)
        return lanes

    def machine_changes(self, seq: int, limit: int = 1000) -> list[tuple[str, dict[str, Any], int]]:
        """Each machine row folded after stream position `seq`, oldest first, as (machine, agent, seq)."""
        statement = (
            select(machine_tasks.c.machine, machine_tasks.c.agent, machine_tasks.c.seq)
            .where(machine_tasks.c.seq > seq)
            .order_by(machine_tasks.c.seq)
            .limit(limit)
        )
        with self._engine.connect() as db:
            return [tuple(row) for row in db.execute(statement).all()]

    def machine_position(self) -> int:
        """The stream position of the newest machine row; 0 when none has one."""
        with self._engine.connect() as db:
            return db.execute(select(func.max(machine_tasks.c.seq))).scalar() or 0

    def _machine_rows(self, machine: str | None, since: float | None) -> list[tuple[str, dict[str, Any], int]]:
        statement = select(machine_tasks.c.machine, machine_tasks.c.agent, machine_tasks.c.seq)
        if machine is not None:
            statement = statement.where(machine_tasks.c.machine == machine)
        if since is not None:
            statement = statement.where(machine_tasks.c.active_at >= since)
        with self._engine.connect() as db:
            return [tuple(row) for row in db.execute(statement).all()]

    def _summaries(self, statement: Select[Any]) -> list[dict[str, Any]]:
        with self._engine.connect() as db:
            return [dict(item) for item in db.execute(statement).mappings()]

    def _ids(self, statement: Select[Any]) -> list[str]:
        with self._engine.connect() as db:
            return list(db.execute(statement).scalars())
