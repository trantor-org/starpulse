"""StarPulse's history store: a task's paths, kept past the streams' trim, in a SQLite database.

`database_url` in the config names the SQLite database; without one it is a file beside the config.
StarPulse owns these tables and creates them on first use.

A consumer copies `machine:events` (every entry, task- or run-keyed) into it, a board adapter that reads a
stream may record each lane change it reads. It also keeps the step graphs `push_runs` learns from the pushed run
events, so a restart restores them.
`POST /graphql` reads the paths back through `lane_path` and `machine_path`.
"""

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from sqlalchemy import (
    Column,
    Connection,
    Engine,
    Float,
    Index,
    Integer,
    String,
    Table,
    Text,
    create_engine,
    func,
    or_,
    select,
    update,
)
from sqlalchemy import event as sa_event
from sqlalchemy.dialects import sqlite
from sqlalchemy.exc import OperationalError

from starpulse.event_log import events as machine_events
from starpulse.event_log import lane_events
from starpulse.event_log.checkpoints import Checkpoints
from starpulse.event_log.event_log import WAL_SIZE_LIMIT, EventLog, insert_event
from starpulse.event_log.lane_import import Change
from starpulse.event_log.migrate import require_migrated
from starpulse.event_log.readmodel import task_uuid
from starpulse.event_log.store import EventStore
from starpulse.event_log.tables import machine_events as _machine_events
from starpulse.event_log.tables import metadata
from starpulse.event_log.wake import RETRY_DELAY, StopEvent
from starpulse.flow_metrics.adapters.outbound import summaries  # noqa: F401 - declares the dead step-summaries table until a migration drops it
from starpulse.machine_engine.model.transitions import Table as Transitions
from starpulse.machine_engine.model.transitions import lane_id

__all__ = ["HistoryStore", "machine_steps"]

logger = logging.getLogger(__name__)

#: How long a write waits on another process's write lock, in seconds. Every worker opens the store at `serve` start,
#: and one migrating a large history holds the lock for seconds.
_SQLITE_BUSY_TIMEOUT = 60.0
#: How many event ids one statement asks the lane history for, under SQLite's limit on bound parameters.
_TASKS_PER_QUERY = 500

_lane_changes = Table(
    "starpulse_lane_changes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String, nullable=False, unique=True),
    Column("task", String, nullable=False),
    Column("old_status", String),
    Column("new_status", String, nullable=False),
    Column("observed_at", Float, nullable=False),
    Column("actor", String),
    Column("task_uuid", String),
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
def _last_lane(db: Connection, task: str, source_name: str | None) -> str | None:
    """The status of the task's latest lane change; with a `source_name`, of the change that source sent."""
    c = _lane_changes.c
    query = select(c.new_status).where(c.task == task).order_by(c.observed_at.desc(), c.id.desc()).limit(1)
    if source_name is not None:
        query = query.where(c.event_id.startswith(f"{source_name}/", autoescape=True))
    return db.execute(query).scalar()


def _holds_move(db: Connection, task: str, source_name: str | None, status: str, at: float) -> bool:
    """Whether the history holds the task's move into `status` at `at`: a second writer of the move adds nothing."""
    c = _lane_changes.c
    query = select(c.id).where(c.task == task, c.new_status == status, c.observed_at == at).limit(1)
    if source_name is not None:
        query = query.where(c.event_id.startswith(f"{source_name}/", autoescape=True))
    return db.execute(query).first() is not None


def _rechain(db: Connection, tasks: Iterable[str]) -> None:
    """Chain each task's rows, per source, off the row before them: imported rows older than live ones sit in front."""
    c = _lane_changes.c
    held = select(c.id, c.task, c.event_id, c.old_status, c.new_status).where(c.task.in_(list(tasks)))
    rows = db.execute(held.order_by(c.task, *_LANE_ORDER))
    before: dict[tuple[str, str], str | None] = {}
    for id_, task, event_id, old, new in rows.all():
        key = task, event_id.partition("/")[0] if "/" in event_id else ""
        if old != before.get(key):
            db.execute(update(_lane_changes).where(c.id == id_).values(old_status=before.get(key)))
        before[key] = new


def _held_ids(db: Connection, event_ids: list[str]) -> set[str]:
    """The `event_ids` the lane history holds."""
    c = _lane_changes.c
    held: set[str] = set()
    for start in range(0, len(event_ids), _TASKS_PER_QUERY):
        held.update(
            db.execute(select(c.event_id).where(c.event_id.in_(event_ids[start : start + _TASKS_PER_QUERY]))).scalars()
        )
    return held


def lane_changes(rows: list[tuple[float, str | None, str, str | None]]) -> list[dict]:
    """`{at, from, to}` for each `(at, old, new, actor)` row that changed lane, with `by` where a write named its actor."""
    return [
        {"at": at, "from": old, "to": new, **({"by": actor} if actor else {})}
        for at, old, new, actor in rows
        if old != new
    ]


def machine_steps(machine: dict, rows: list[tuple[float, str]]) -> tuple[list[dict], int]:
    """A task's `(at, event)` rows on `machine`, oldest first, as `{at, event, state}` and their count.

    Each event is placed by the rule the machine level uses (`domain.transitions.Table.target`), so a trace that starts
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


def _sqlite_tune(dbapi_connection: Any, _record: Any) -> None:
    """Bound the -wal file and refresh the planner statistics, as each pooled connection opens.

    The server exits without disposing its pool, so a connection-close hook never runs; opening is when SQLite's own
    guidance runs `optimize`, and 0x10000 makes it look at every table, not only those this connection has touched.
    """
    dbapi_connection.execute(f"PRAGMA journal_size_limit={WAL_SIZE_LIMIT}")
    dbapi_connection.execute("PRAGMA optimize=0x10002")


class HistoryStore:
    """The history in one database; consumer threads write and request threads read, each through its own connection.

    `machines` are the machines the page draws, which place a task's events on its path. `retention_days` is the age
    past which `task_events` reads nothing, as the event log prunes (None: no cutoff).
    """

    def __init__(
        self, url: str, machines: Mapping[str, dict], engine: Engine | None = None, *, retention_days: int | None = None
    ) -> None:
        self.engine = engine or create_engine(url, connect_args={"timeout": _SQLITE_BUSY_TIMEOUT})
        sa_event.listen(self.engine, "connect", _sqlite_tune)
        self._machines = machines
        self._retention = None if retention_days is None else retention_days * 86400.0
        require_migrated(self.engine)

    def _insert(self, table: Table):
        return sqlite.insert(table)

    @property
    def checkpoints(self) -> Checkpoints:
        """How far each reader of the log got, so a restart resumes after the last entry it recorded."""
        return Checkpoints(self.engine)

    def record_machine(self, entry_id: str, fields: dict, *, cursor: int | None = None) -> None:
        """Write one machine event; one the store already holds is a no-op.

        `cursor`, the event's id in the log, is saved in the same transaction, so the store never holds an event
        its cursor has not passed or a cursor past an event it lacks.
        """
        row = {
            "event_id": fields.get("event_id") or entry_id,
            "task": fields.get("task"),
            "run": fields.get("run"),
            "machine": fields["machine"],
            "event": fields["event"],
            "actor": fields.get("actor"),
            "occurred_at": float(fields["time"]),
            "sha": (fields.get("data") or {}).get("sha"),
        }
        with self.engine.begin() as db:
            insert = self._insert(_machine_events).values(row | {"task_uuid": task_uuid.of(row["task"])}).on_conflict_do_nothing()
            db.execute(insert)
            if cursor is not None:
                self.checkpoints.save(machine_events.STREAM, cursor, conn=db)

    def record_lane(
        self,
        event_id: str,
        task: str,
        status: str,
        at: float,
        *,
        cursor: int | None = None,
        event: Mapping[str, Any] | None = None,
        actor: str | None = None,
    ) -> bool:
        """Write a task's lane change; True when a row was written. The status is kept as
        its lane id (`In Progress` is `in_progress`). One that repeats the task's last (a reconcile) is no change, and
        neither is an event id or a move (task, lane, time) the store already holds: a second writer adds no row.

        A source's change (`<source>/<id>`) repeats only the last status of the same source's task: two sources may
        key a task alike. `cursor`, the entry's id in the log, is saved in the same transaction, as is the lane `event`
        (the `board:lanes` fields, under `event_id`) a change writes: both land or neither does. The row keeps the `actor`
        that made the change, else the `event`'s.
        """
        with self.engine.begin() as db:
            written = self._fold_lane(db, event_id, task, status, at, actor or (event or {}).get("actor"))
            if written and event is not None:
                insert_event(db, lane_events.STREAM, event, event_id)
            if cursor is not None:
                self.checkpoints.save(lane_events.STREAM, cursor, conn=db)
        return written

    def _fold_lane(
        self, db: Connection, event_id: str, task: str, status: str, at: float, actor: str | None = None
    ) -> bool:
        status = lane_id(status)
        name, slash, _ = event_id.partition("/")
        source = name if slash and name else None
        last = _last_lane(db, task, source)
        if (last is not None and lane_id(last) == status) or _holds_move(db, task, source, status, at):
            return False
        change = self._insert(_lane_changes).values(
            event_id=event_id,
            task=task,
            task_uuid=task_uuid.of(task),
            old_status=last,
            new_status=status,
            observed_at=at,
            actor=actor,
        )
        return db.execute(change.on_conflict_do_nothing().returning(_lane_changes.c.id)).first() is not None

    def import_lanes(self, changes: Iterable[Change]) -> int:
        """Add the lane changes of an earlier history, each once: how many of them the store holds that it did not.

        A change is written as the board's own event id names it, so one the store holds is not written again, and a
        move the store holds under another id (task, lane, time) or a change into the lane its task was already in
        adds nothing. Changes may be older than the rows the store holds, so the touched tasks are chained again.
        """
        ordered = sorted(changes, key=lambda change: change.at)
        ids = [change.event_id for change in ordered]
        last: dict[tuple[str, str], str] = {}
        with self.engine.begin() as db:
            held = _held_ids(db, ids)
            for event_id, task, lane, at in ordered:
                status = lane_id(lane)
                name, slash, _ = event_id.partition("/")
                source = name if slash else ""
                if last.get((source, task)) == status:
                    continue
                last[source, task] = status
                if _holds_move(db, task, name if slash and name else None, status, at):
                    continue
                row = {"event_id": event_id, "task": task, "old_status": None, "new_status": status, "observed_at": at}
                db.execute(self._insert(_lane_changes).values(row | {"task_uuid": task_uuid.of(task)}).on_conflict_do_nothing())
            _rechain(db, {task for _, task in last})
        with self.engine.connect() as db:
            return len(_held_ids(db, ids) - held)

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

    def forget_workflow(self, workflow: str) -> None:
        """Drop the steps learned for a pushed workflow."""
        with self.engine.begin() as db:
            db.execute(_learned_steps.delete().where(_learned_steps.c.workflow == workflow))

    def learned_graphs(self) -> dict[str, dict[str, list[str]]]:
        """Each pushed workflow's steps, in the order they were first reported, with the steps each waits on."""
        steps = _learned_steps.c
        with self.engine.connect() as db:
            rows = db.execute(select(steps.workflow, steps.step, steps.depends).order_by(steps.id)).all()
        graphs: dict[str, dict[str, list[str]]] = {}
        for workflow, step, depends in rows:
            graphs.setdefault(workflow, {})[step] = json.loads(depends)
        return graphs

    def lane_rows(self, since: float | None = None) -> list[tuple[str, float, str | None, str]]:
        """`(task, at, from, to)` for every lane change of every task at or after epoch `since` (None: all), oldest
        first."""
        c = _lane_changes.c
        query = select(c.task, c.observed_at, c.old_status, c.new_status).order_by(*_LANE_ORDER)
        if since is not None:
            query = query.where(c.observed_at >= since)
        with self.engine.connect() as db:
            rows = db.execute(query).all()
        return [tuple(row) for row in rows]

    def machine_event_rows(self, since: float | None = None) -> list[tuple[str, str, float, str]]:
        """`(machine, key, at, event)` for every machine event at or after epoch `since` (None: all), oldest first; the key is
        the task, or the run when the event moved one."""
        c = _machine_events.c
        query = select(c.machine, func.coalesce(c.task, c.run), c.occurred_at, c.event).order_by(*_STEP_ORDER)
        if since is not None:
            query = query.where(c.occurred_at >= since)
        return self._read(query)

    def lane_changes(self) -> list[tuple[str, str, str, float]]:
        """`(event_id, task, lane, at)` for every lane change of every task, oldest first."""
        c = _lane_changes.c
        return self._read(select(c.event_id, c.task, c.new_status, c.observed_at).order_by(*_LANE_ORDER))

    def _read(self, query):
        with self.engine.connect() as db:
            return [tuple(row) for row in db.execute(query).all()]

    def lane_path(self, task: str) -> list[dict]:
        """`{at, from, to}` for each time the task changed lane, oldest first; a task never seen has none."""
        c = _lane_changes.c
        with self.engine.connect() as db:
            rows = db.execute(
                select(c.observed_at, c.old_status, c.new_status, c.actor).where(c.task == task).order_by(*_LANE_ORDER)
            ).all()
        return lane_changes([tuple(row) for row in rows])

    def plan_revisions(self, task: str) -> int:
        """How many `PlanRevised` Events the task's History holds: plans rewritten after work began."""
        return sum(1 for event in EventStore(self.engine).read("task", task) if event.type == "PlanRevised")

    def machine_path(self, task: str, flow: str) -> tuple[list[dict], int]:
        """The events of the task, or of the run with that id, on `flow` as `{at, event, state}` in order, and their count."""
        c = _machine_events.c
        with self.engine.connect() as db:
            rows = db.execute(
                select(c.occurred_at, c.event)
                .where(or_(c.task == task, c.run == task), c.machine == flow)
                .order_by(*_STEP_ORDER)
            ).all()
        return machine_steps(self._machines[flow], [tuple(row) for row in rows])

    def task_events(self, task: str, since: float, now: float) -> list[dict]:
        """The task's events on every machine since epoch `since`, oldest first, as `{at, machine, event, from, to}`.

        Each machine's states are placed from the oldest event kept, so an event's `from` is where the task stood
        before it even when that came before `since`. Events older than the retention before `now` are not read.
        """
        c = _machine_events.c
        floor = since if self._retention is None else max(since, now - self._retention)
        query = (
            select(c.machine, c.occurred_at, c.event)
            .where(c.task == task, c.machine.in_(self._machines))
            .order_by(*_STEP_ORDER)
        )
        if self._retention is not None:
            query = query.where(c.occurred_at >= now - self._retention)
        with self.engine.connect() as db:
            rows = db.execute(query).all()
        tables = {machine: Transitions(self._machines[machine]) for machine in {row[0] for row in rows}}
        states = {machine: table.initial for machine, table in tables.items()}
        events = []
        for machine, at, event in rows:
            before = states[machine]
            states[machine] = tables[machine].target(before, event) or before
            if at >= floor:
                events.append({"at": at, "machine": machine, "event": event, "from": before, "to": states[machine]})
        return events


def record_machine_events(store: HistoryStore, log: EventLog, stop: StopEvent) -> None:
    """Copy the log's machine events into `store` until `stop`, resuming after the cursor the store holds.

    A store with no cursor replays what the log retains. Each entry is written with its cursor in one transaction,
    so a restart neither skips nor repeats one, and rows pruned unread are a gap (`Tail`). A database that cannot be
    reached is the sink down, not the entry bad, so the entry is read again on the next poll.
    """
    _copy(store, log, stop, machine_events.STREAM, store.record_machine)


def _copy(
    store: HistoryStore,
    log: EventLog,
    stop: StopEvent,
    stream: str,
    write: Callable[..., None],
) -> None:
    while not stop.is_set():
        try:
            after = store.checkpoints.load(stream)[0]
            break
        except OperationalError as exc:
            logger.warning("history: cannot read the %s cursor, retrying in %ss: %s", stream, RETRY_DELAY, exc)
            # adr-exempt: retry
            stop.wait(RETRY_DELAY)
    else:
        return
    log.tail(stream, after=after).run(
        lambda entry: write(entry.event_id, entry.fields, cursor=entry.id),
        stop,
        transient=(OperationalError,),
    )
