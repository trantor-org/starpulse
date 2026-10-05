"""StarPulse's history store: a task's paths, kept past the streams' trim, in any SQLAlchemy database.

`database_url` in the config names the database; without one it is a SQLite file beside the config. A
Postgres URL (`postgresql+psycopg://...`, with the `postgres` extra installed) keeps it on a server instead.
StarPulse owns these tables and creates them on first use.

A consumer copies `machine:events` (every entry, task- or run-keyed) into it, a board adapter that reads a
stream may record each lane change it reads, and a trim past an entry a consumer never read is recorded as a
gap. It also keeps the step graphs `push_runs` learns from `starpulse emit`, so a restart restores them.
`/api/history` reads the paths back through `lane_path` and `machine_path`.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from sqlalchemy import (
    Column,
    Engine,
    Float,
    Index,
    Integer,
    String,
    Table,
    Text,
    bindparam,
    create_engine,
    select,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import OperationalError

from starpulse import events as machine_events
from starpulse.gap_consumer import GapWatchingConsumer
from starpulse.machine_tasks import Table as Transitions
from starpulse.tables import gaps as _gaps
from starpulse.tables import metadata

__all__ = ["History", "machine_steps"]

#: The file a config without `database_url` keeps its history in, beside the config.
DEFAULT_FILE = "starpulse-history.sqlite"

_machine_events = Table(
    "starpulse_machine_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String, nullable=False, unique=True),
    Column("task", String),
    Column("run", String),
    Column("machine", String, nullable=False),
    Column("event", String, nullable=False),
    Column("actor", String),
    Column("occurred_at", Float, nullable=False),
    Index("ix_starpulse_machine_events_task", "task", "machine", "occurred_at"),
)
_lane_changes = Table(
    "starpulse_lane_changes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String, nullable=False, unique=True),
    Column("task", String, nullable=False),
    Column("old_status", String),
    Column("new_status", String, nullable=False),
    Column("observed_at", Float, nullable=False),
    Index("ix_starpulse_lane_changes_task", "task", "observed_at"),
)
_learned_steps = Table(
    "starpulse_learned_steps",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("workflow", String, nullable=False),
    Column("step", String, nullable=False),
    Column("depends", Text, nullable=False),
    Index("ux_starpulse_learned_steps", "workflow", "step", unique=True),
)
#: A path's order: by time, and the earlier insert first when two rows share one.
_LANE_ORDER = (_lane_changes.c.observed_at, _lane_changes.c.id)
_STEP_ORDER = (_machine_events.c.occurred_at, _machine_events.c.id)
#: A task's last lane: its latest observation, the later insert on a tie.
_LAST_LANE = (
    select(_lane_changes.c.new_status)
    .where(_lane_changes.c.task == bindparam("task"))
    .order_by(_lane_changes.c.observed_at.desc(), _lane_changes.c.id.desc())
    .limit(1)
)


class History(Protocol):
    """Where `/api/history` reads a task's paths from."""

    def lane_path(self, task: str) -> list[dict]: ...

    def machine_path(self, task: str, flow: str) -> tuple[list[dict], int]: ...


def database_url(configured: str | None, directory: Path) -> str:
    """The configured URL, else a SQLite file `DEFAULT_FILE` in `directory`."""
    return configured or f"sqlite:///{(directory / DEFAULT_FILE).resolve()}"


def lane_changes(rows: list[tuple[float, str | None, str]]) -> list[dict]:
    """`{at, from, to}` for each `(at, old, new)` row that changed lane."""
    return [{"at": at, "from": old, "to": new} for at, old, new in rows if old != new]


def machine_steps(machine: dict, rows: list[tuple[float, str]]) -> tuple[list[dict], int]:
    """A task's `(at, event)` rows on `machine`, oldest first, as `{at, event, state}` and their count.

    Each event is placed by the rule the machine level uses (`machine_tasks.Table.target`), so a trace that starts
    mid-life or lacks the judged events still reaches where the task is. A row is never dropped: one the machine
    cannot place leaves the task where it was, so the count is the row count.
    """
    table = Transitions(machine)
    path: list[dict] = []
    state = table.initial
    for at, event in rows:
        state = table.target(state, event) or state
        path.append({"at": at, "event": event, "state": state})
    return path, len(path)


class HistoryStore:
    """The history in one database; consumer threads write and request threads read, each through its own connection.

    `machines` are the machines the page draws, which place a task's events on its path.
    """

    def __init__(self, url: str, machines: Mapping[str, dict], engine: Engine | None = None) -> None:
        self.engine = engine or create_engine(url)
        self._machines = machines
        # pragma: no mutate start — SQLite compiles the postgresql insert's ON CONFLICT alike
        self._dialect = postgresql if self.engine.dialect.name == "postgresql" else sqlite
        # pragma: no mutate end
        metadata.create_all(self.engine)
        #: One group per database, so two views on one Redis each fill their own, and a new database replays what the
        #: stream still holds into it (a redelivered entry is a no-op).
        self.group = f"starpulse-history-{hashlib.sha1(url.encode()).hexdigest()[:8]}"

    def _insert(self, table: Table):
        return self._dialect.insert(table)

    def record_machine(self, entry_id: str, fields: dict) -> None:
        """Write one `machine:events` entry; one the store already holds is a no-op."""
        row = {
            "event_id": fields.get("event_id") or entry_id,
            "task": fields.get("task"),
            "run": fields.get("run"),
            "machine": fields["machine"],
            "event": fields["event"],
            "actor": fields.get("actor"),
            "occurred_at": float(fields["time"]),
        }
        with self.engine.begin() as db:
            db.execute(self._insert(_machine_events).values(row).on_conflict_do_nothing())

    def record_lane(self, event_id: str, task: str, status: str, at: float) -> None:
        """Write a task's lane change; a status that repeats the task's last one (a reconcile) is no change."""
        with self.engine.begin() as db:
            last = db.execute(_LAST_LANE, {"task": task}).scalar()
            if last != status:
                db.execute(
                    self._insert(_lane_changes)
                    .values(event_id=event_id, task=task, old_status=last, new_status=status, observed_at=at)
                    .on_conflict_do_nothing()
                )

    def record_gap(self, stream: str, after_id: str, before_id: str, lost: int) -> None:
        """Note that `lost` entries of `stream` between `after_id` and `before_id` were trimmed unread."""
        insert = self._insert(_gaps).values(
            stream=stream, after_id=after_id, before_id=before_id, lost=lost, noted_at=time.time()
        )
        with self.engine.begin() as db:
            db.execute(
                insert.on_conflict_do_update(
                    index_elements=["stream", "after_id"],
                    set_={"before_id": insert.excluded.before_id, "lost": insert.excluded.lost},
                )
            )

    def record_step(self, workflow: str, step: str, depends: list[str] | None) -> None:
        """Remember a step of a pushed workflow; `depends` None keeps the dependencies already known."""
        insert = self._insert(_learned_steps).values(
            workflow=workflow, step=step, depends=json.dumps([] if depends is None else depends)
        )
        keys = ["workflow", "step"]
        with self.engine.begin() as db:
            if depends is None:
                db.execute(insert.on_conflict_do_nothing())
            else:
                db.execute(insert.on_conflict_do_update(index_elements=keys, set_={"depends": insert.excluded.depends}))

    def learned_graphs(self) -> dict[str, dict[str, list[str]]]:
        """Each pushed workflow's steps, in the order they were first reported, with the steps each waits on."""
        steps = _learned_steps.c
        with self.engine.connect() as db:
            # pragma: no mutate start — a fresh test table scans in insertion order
            rows = db.execute(select(steps.workflow, steps.step, steps.depends).order_by(steps.id)).all()
            # pragma: no mutate end
        graphs: dict[str, dict[str, list[str]]] = {}
        for workflow, step, depends in rows:
            graphs.setdefault(workflow, {})[step] = json.loads(depends)
        return graphs

    def gaps(self) -> list[dict]:
        """Every recorded gap as `{stream, after_id, before_id, lost}`, oldest first."""
        g = _gaps.c
        with self.engine.connect() as db:
            # pragma: no mutate start — a fresh test table scans in insertion order
            rows = db.execute(select(g.stream, g.after_id, g.before_id, g.lost).order_by(g.id)).all()
            # pragma: no mutate end
        return [{"stream": s, "after_id": a, "before_id": b, "lost": n} for s, a, b, n in rows]

    def lane_path(self, task: str) -> list[dict]:
        """`{at, from, to}` for each time the task changed lane, oldest first; a task never seen has none."""
        c = _lane_changes.c
        with self.engine.connect() as db:
            rows = db.execute(
                select(c.observed_at, c.old_status, c.new_status).where(c.task == task).order_by(*_LANE_ORDER)
            ).all()
        return lane_changes([tuple(row) for row in rows])

    def machine_path(self, task: str, flow: str) -> tuple[list[dict], int]:
        """The task's events on `flow` as `{at, event, state}` in order, and their count."""
        c = _machine_events.c
        with self.engine.connect() as db:
            rows = db.execute(
                select(c.occurred_at, c.event).where(c.task == task, c.machine == flow).order_by(*_STEP_ORDER)
            ).all()
        return machine_steps(self._machines[flow], [tuple(row) for row in rows])


def build_machine_recorder(store: HistoryStore) -> GapWatchingConsumer:
    """The consumer that copies `machine:events` into `store`, from the oldest entry the stream still holds.

    A database that cannot be reached is the sink down, not the entry bad, so the entry stays pending.
    """
    stream = machine_events.STREAM
    return GapWatchingConsumer.from_env(
        machine_events.REDIS_ENV_PREFIX,
        stream=stream,
        group=store.group,
        consumer=store.group,
        handler=store.record_machine,
        transient=(OperationalError,),
        on_gap=lambda after, before, lost: store.record_gap(stream, after, before, lost),
    )
