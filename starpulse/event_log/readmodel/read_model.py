"""The read model's reads: what the page, the agent CLI, search and the Scheduler ask of the Task tables."""

import threading
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection, Engine, Select, func, or_, select, union_all

from starpulse.event_log.readmodel import queries, rows, task_uuid
from starpulse.event_log.readmodel.declared import Declared
from starpulse.event_log.readmodel.fold import Row
from starpulse.event_log.readmodel.tables import board_keys, machine_tasks


class ReadModel:
    def __init__(self, engine: Engine, declared: dict[str, Declared] | None = None) -> None:
        self._engine = engine
        self._declared = declared or {}
        self._held = threading.local()

    @contextmanager
    def pinned(self) -> Iterator[None]:
        """Within the block this thread's reads share one pooled connection, so a pass of many small reads checks out
        once, never waiting on the pool's lock for each. Each read still sees the database as it stands, as a statement
        of its own does; the block is re-entrant."""
        if getattr(self._held, "db", None) is not None:
            yield
            return
        with self._engine.connect() as db:
            self._held.db = db
            try:
                yield
            finally:
                self._held.db = None

    @contextmanager
    def _reading(self) -> Iterator[Connection]:
        if (held := getattr(self._held, "db", None)) is not None:
            yield held
            return
        with self._engine.connect() as db:
            yield db

    def task(self, task_id: str) -> Row | None:
        """The Task's whole row, archived or not, found by its id in any case, else by its UUID or an alias; None when it has none."""
        with self._reading() as db:
            if found := rows.load(db, task_id) or rows.load_any_case(db, task_id):
                return found
            named = db.execute(
                select(board_keys.c.task_id).where(board_keys.c.token.in_((task_id, task_id.lower())))
            ).scalar()
            return None if named is None else rows.load(db, named)

    def resolve(self, token: str) -> str | None:
        """The id of the Task that `token` names, as its id in any case, its UUID or an alias; None when it names none."""
        found = self.task(token)
        return None if found is None else str(found["id"])

    def snapshot(self, done: str, since: float, only: str | None = None) -> list[dict[str, Any]]:
        """The live Tasks (`queries.live`: unarchived, not done or changed since `since`) as summaries with their
        Acceptance Criteria, in id order; `only` limits them to that one Task, when it is live."""
        summaries = self._summaries(queries.snapshot(done, since, only))
        by_task: dict[str, list[dict[str, Any]]] = {summary["id"]: [] for summary in summaries}
        for item in self._summaries(queries.live_criteria(done, since, only)):
            by_task.get(item.pop("task_id"), []).append(item)
        return [summary | {"criteria": by_task[summary["id"]]} for summary in summaries]

    def archived(self, before: float | None, limit: int, milestone: str | None = None) -> list[dict[str, Any]]:
        """Up to `limit` archived Tasks changed before `before` (None: any time), newest first, of `milestone` when given."""
        return self._summaries(queries.archived(before, limit, milestone))

    def dependencies_of(self, ids: Collection[str]) -> dict[str, list[str]]:
        """The dependencies of each Task `ids` names, an id of any case (Task ids are upper case), archived Tasks included."""
        wanted = {name for task in ids for name in (task, task.upper())}
        return {
            item["id"]: list(item["dependencies"] or [])
            for item in self._summaries(queries.dependencies_of(wanted))
        }

    def aliased(self) -> dict[str, str]:
        """The Task id behind each alias a Task lists in its meta, archived Tasks included."""
        return {
            alias: item["id"]
            for item in self._summaries(queries.titled())
            for alias in (item["meta"] or {}).get("aliases") or []
        }

    def titled(self, ids: Collection[str] | None = None) -> dict[str, dict[str, Any]]:
        """Every Task's `title`, `labels`, `milestone`, `profile` and `members` by id, archived Tasks included, or those
        of `ids` alone; an unset milestone or profile is None."""
        return {
            item["id"]: {
                "title": item["title"],
                "labels": item["labels"],
                "milestone": item["milestone"] or None,
                "profile": (item["meta"] or {}).get("profile") or None,
                "members": (item["meta"] or {}).get("members") or {},
            }
            for item in self._summaries(queries.titled(ids))
        }

    def with_field(self, name: str, value: object) -> list[str]:
        """The ids of unarchived Tasks whose queried declared field `name` equals `value`; KeyError when not queried."""
        field = self._declared.get(name)
        if field is None or not field.queried:
            raise KeyError(name)
        return self._ids(queries.with_field(field.column, value))

    def linked(self, uuids: Collection[str], roles: Collection[str]) -> dict[str, list[tuple[str, str]]]:
        """The `(role, reference)` of each link of `roles` that each task holds, oldest first, by the task's UUID; a task with none is absent."""
        found: dict[str, list[tuple[str, str]]] = {}
        if not uuids:
            return found
        with self._reading() as db:
            for task, role, ref in db.execute(queries.linked(uuids, roles)):
                found.setdefault(task, []).append((role, ref))
        return found

    def citing(self, ref: str) -> list[str]:
        """The ids of unarchived Tasks with a `delivers` or `cites` link to the change `ref`, in id order."""
        return self._ids(queries.citing(ref))

    def held_states(self) -> set[str]:
        """The states unarchived Tasks hold, Done ones of any age included."""
        return set(self._ids(queries.held_states()))

    def held_done(self, done: str) -> list[str]:
        """The ids of unarchived Done Tasks of any age, in id order."""
        return self._ids(queries.held_done(done))

    def milestone_done(self, done: str, since: float) -> dict[str, int]:
        """How many Done Tasks last changed before `since` each milestone holds, the ones `snapshot` leaves out."""
        with self._reading() as db:
            return {milestone: count for milestone, count in db.execute(queries.milestone_done(done, since))}

    def cold_done(self, done: str, since: float, only: str | None = None) -> dict[str, str]:
        """The milestone of each Done Task `milestone_done` counts, by id; `only` limits them to one Task."""
        with self._reading() as db:
            return {task: milestone for task, milestone in db.execute(queries.cold_done(done, since, only))}

    def archived_ids(self) -> set[str]:
        """The ids of every archived Task."""
        return set(self._ids(queries.archived_ids()))

    def archived_since(self, since: float) -> int:
        """How many Tasks were archived at or after `since`."""
        with self._reading() as db:
            return db.execute(queries.archived_since(since)).scalar_one()

    def settled_done(self, done: str, since: float, only: str | None = None) -> list[dict[str, Any]]:
        """The archived Done Tasks changed at or after `since`, with their meta, in id order; `only` limits them to one."""
        return self._summaries(queries.settled_done(done, since, only))

    def ready(self, state: str, done: str, only: str | None = None) -> list[str]:
        """The ids of unarchived Tasks in `state` whose dependencies are all in `done`; `only` limits it to that id."""
        return self._ids(queries.ready(state, done, only))

    def since(self, seq: int, limit: int = 1000) -> list[dict[str, Any]]:
        """Summaries of the Tasks changed after `seq`, archived ones included, in the order they changed."""
        return self._summaries(queries.since(seq, limit))

    def position(self) -> int:
        """The stream position of the newest change; 0 when no Task has one."""
        with self._reading() as db:
            return db.execute(queries.position()).scalar() or 0

    def machine_tasks(self, machine: str, since: float | None = None) -> list[dict[str, Any]]:
        """Each agent `machine` holds that it placed at or after `since` (None: every one), as the page draws it."""
        return [agent for _, agent, _ in self._machine_rows(machine, since)]

    def machine_task_ids(self, machine: str, since: float | None = None) -> list[str]:
        """The ids `machine` placed at or after `since` (None: every one), read without their records."""
        statement = select(machine_tasks.c.task).where(machine_tasks.c.machine == machine)
        if since is not None:
            statement = statement.where(machine_tasks.c.active_at >= since)
        return self._ids(statement)

    def machine_task(self, machine: str, task: str) -> dict[str, Any] | None:
        """The agent `machine` holds for `task`, or None when it places none."""
        statement = select(machine_tasks.c.agent).where(machine_tasks.c.machine == machine, machine_tasks.c.task_uuid == task_uuid.of(task))
        with self._reading() as db:
            return db.execute(statement).scalar()

    def machine_lanes(
        self, since: float | None = None, keep_open: str | None = None, live_since: float | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Every machine's agents placed at or after `since`, keyed by machine; a machine with none is absent.

        `keep_open` is the Board's done lane: an agent placed earlier stays while its Task is live (`queries.live`):
        unarchived and not done, or done at or after `live_since`.
        """
        lanes: dict[str, list[dict[str, Any]]] = {}
        for machine, agent, _ in self._machine_rows(None, since, keep_open, live_since):
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
        with self._reading() as db:
            return [tuple(row) for row in db.execute(statement).all()]

    def machine_position(self) -> int:
        """The stream position of the newest machine row; 0 when none has one."""
        with self._reading() as db:
            return db.execute(select(func.max(machine_tasks.c.seq))).scalar() or 0

    def _machine_rows(
        self, machine: str | None, since: float | None, keep_open: str | None = None, live_since: float | None = None
    ) -> list[tuple[str, dict[str, Any], int]]:
        mt = machine_tasks.c
        statement = select(mt.machine, mt.task, mt.agent, mt.seq)
        if machine is not None:
            statement = statement.where(mt.machine == machine)
        if since is None:
            statement = statement.order_by(mt.machine, mt.task)
        elif keep_open is None:
            statement = statement.where(mt.active_at >= since)
        elif live_since is None:
            raise ValueError("keep_open needs live_since, the start of the live window")
        else:
            live = queries.live_uuids(keep_open, live_since)
            statement = union_all(
                statement.where(mt.task_uuid.in_(live)),
                statement.where(mt.active_at >= since, or_(mt.task_uuid.is_(None), mt.task_uuid.not_in(live))),
            )
        with self._reading() as db:
            found = [tuple(row) for row in db.execute(statement).all()]
        if since is not None:
            # Sorted here: an ORDER BY in the windowed SQL makes SQLite walk every row's primary key, not the `active_at` index.
            found.sort(key=lambda row: row[:2])
        return [(machine, agent, seq) for machine, _, agent, seq in found]

    def _summaries(self, statement: Select[Any]) -> list[dict[str, Any]]:
        with self._reading() as db:
            return [dict(item) for item in db.execute(statement).mappings()]

    def _ids(self, statement: Select[Any]) -> list[str]:
        with self._reading() as db:
            return list(db.execute(statement).scalars())
