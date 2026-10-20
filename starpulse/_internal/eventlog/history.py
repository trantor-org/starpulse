"""StarPulse's history store: a task's paths, kept past the streams' trim, in any SQLAlchemy database.

`database_url` in the config names the database; without one it is a SQLite file beside the config. A
Postgres URL (`postgresql+psycopg://...`, with the `postgres` extra installed) keeps it on a server instead.
StarPulse owns these tables and creates them on first use.

A consumer copies `machine:events` (every entry, task- or run-keyed) into it, a board adapter that reads a
stream may record each lane change it reads, and a trim past an entry a consumer never read is recorded as a
gap. It also keeps the step graphs `push_runs` learns from the pushed run events, so a restart restores them.
`/api/history` reads the paths back through `lane_path` and `machine_path`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import (
    Column,
    Connection,
    Engine,
    Float,
    Index,
    Integer,
    Select,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy import event as sa_event
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from starpulse._internal.config.config import discover, load
from starpulse._internal.config.level import Level
from starpulse._internal.eventlog import events as machine_events
from starpulse._internal.eventlog import lane_events, lane_repair
from starpulse._internal.eventlog.checkpoints import Checkpoints
from starpulse._internal.eventlog.event_log import DEFAULT_POLL_INTERVAL, EventLog, create_tables, insert_event
from starpulse._internal.eventlog.lane_import import Change
from starpulse._internal.eventlog.level_metrics import AGING_WINDOW_S, Run, RunWindow, state_roles
from starpulse._internal.eventlog.summaries import (
    BOARD,
    SUMMARY_TABLES,
    Fold,
    Summariser,
    cases,
    count_lanes,
    lane_intervals,
    lanes,
    read_case,
    source,
    summary_basis,
    write_lane,
    write_step,
)
from starpulse._internal.eventlog.tables import gaps as _gaps
from starpulse._internal.eventlog.tables import metadata
from starpulse._internal.machines.stays import Dwell, LaneStays, Stay
from starpulse._internal.machines.transitions import Table as Transitions
from starpulse._internal.machines.transitions import lane_id

__all__ = ["History", "machine_steps"]

logger = logging.getLogger(__name__)

#: How many raw rows a rebuild of the summaries reads at a time.
_CHUNK = 5000
#: How many tasks one statement asks the lane intervals for, under every dialect's limit on bound parameters.
_TASKS_PER_QUERY = 500

#: How long one read of the level's window serves requests, and how many windows (one per level and span asked) are kept.
_WINDOW_BUCKET_S = 60.0
_WINDOWS_KEPT = 8

#: How long one computed level answer serves requests, and how many answers (one per route and query) are kept.
_ANSWER_BUCKET_S = 5.0
_ANSWERS_KEPT = 32
_Answer = tuple[bytes, int]

#: The file a config without `database_url` keeps its history in, beside the config.
DEFAULT_FILE = "starpulse-history.sqlite"

#: The most the -wal file keeps after a checkpoint resets it. SQLite keeps the file at its high-water mark otherwise,
#: so one burst left a 462 MB file holding a few hundred frames.
_WAL_SIZE_LIMIT = 64 * 1024 * 1024

#: How long a write waits on another process's write lock, in seconds. Every worker opens the store at `serve` start,
#: and one rebuilding the summaries of a large history holds the lock for seconds.
_SQLITE_BUSY_TIMEOUT = 60.0

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
    Index("ix_starpulse_machine_events_run", "run", "machine", "occurred_at"),
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
#: When each Waiting task's Start Criteria were first seen all met, for as long as they have stayed met: one row per task.
_criteria_met = Table(
    "starpulse_criteria_met",
    metadata,
    Column("task", String, primary_key=True),
    Column("met_at", Float, nullable=False),
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
#: The id this store sends a hub under each forwarder's cursor name, minted on first use and kept, so a restarted
#: forwarder is the instance the hub bound and a second store, with no row here, is a new one.
_instances = Table(
    "starpulse_forward_instances",
    metadata,
    Column("name", String, primary_key=True),
    Column("instance", String, nullable=False),
)
#: A path's order: by time, and the earlier insert first when two rows share one.
_LANE_ORDER = (_lane_changes.c.observed_at, _lane_changes.c.id)
_STEP_ORDER = (_machine_events.c.occurred_at, _machine_events.c.id)


#: A task's last lane: its latest observation, the later insert on a tie.
def _last_lane(db: Connection, task: str, source_name: str | None) -> str | None:
    """The status of the task's latest lane change; with a `source_name`, of the change that source forwarded."""
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


class History(Protocol):
    """Where `/api/history` reads a task's paths from."""

    def lane_path(self, task: str) -> list[dict]: ...

    def machine_path(self, task: str, flow: str) -> tuple[list[dict], int]: ...


@runtime_checkable
class LaneHistory(History, Protocol):
    """A history that can list every task's lane changes: what the Ledger reads."""

    def lane_rows(self, since: float | None = None) -> list[tuple[str, float, str | None, str]]:
        """`(task, at, from, to)` for every task's lane changes at or after epoch `since` (None: all), oldest first."""
        ...


@runtime_checkable
class HealthHistory(LaneHistory, Protocol):
    """A history that can also answer `/api/analytics/health`: the gaps it recorded as well as the lane changes."""

    def gaps(self) -> list[dict]: ...


@runtime_checkable
class SummarisedHealth(HealthHistory, Protocol):
    """A history that keeps lane summaries, so flow health reads a window of them and not every lane change."""

    def health_stays(self, machine: dict, *, start: float, now: float, stuck_s: float) -> LaneStays: ...


@runtime_checkable
class LevelHistory(History, Protocol):
    """A history that can also answer `/api/level`: each task's trajectory on a machine, by its reporting source."""

    def level_runs(self, flow: str) -> list[Run]: ...


@runtime_checkable
class SummarisedLevel(History, Protocol):
    """A history that keeps lane summaries, so the level reads the runs a window touches and not every lane change."""

    def level_window(self, level: Level, *, now: float, window_s: float) -> RunWindow: ...

    def level_answer(self, level: Level, key: Hashable, *, now: float, compute: Callable[[], _Answer]) -> _Answer:
        """`compute()` for `key`, or the answer an earlier request computed in the same few seconds, as long as no
        summary has been written since."""
        ...


def _in_id_order(db: Connection, query: Select, id_column: Column, after: int = 0) -> Iterator[Mapping[str, Any]]:
    """The rows of `query`, which selects `id`, past id `after` in id order, read a chunk at a time so a write may run
    between them."""
    while rows := db.execute(query.where(id_column > after).limit(_CHUNK)).mappings().all():
        yield from rows
        after = rows[-1]["id"]


def _held_ids(db: Connection, event_ids: list[str]) -> set[str]:
    """The `event_ids` the lane history holds."""
    c = _lane_changes.c
    held: set[str] = set()
    for start in range(0, len(event_ids), _TASKS_PER_QUERY):
        held.update(
            db.execute(select(c.event_id).where(c.event_id.in_(event_ids[start : start + _TASKS_PER_QUERY]))).scalars()
        )
    return held


def database_url(configured: str | None, directory: Path) -> str:
    """The configured URL, else a SQLite file `DEFAULT_FILE` in `directory`."""
    return configured or f"sqlite:///{(directory / DEFAULT_FILE).resolve()}"


def open_event_log(path: Path | None = None) -> EventLog:
    """The event log in the store `serve --config path` keeps its history in, so a producer and the view share it.

    A producer runs from no fixed directory, so it names the config as `serve` does: `path`, else `starpulse.toml`
    in the working directory, else the defaults. Raises `OSError` or `ValueError` for a config that cannot be read.
    """
    path = discover(path)
    return EventLog(database_url(load(path).database_url, path.parent if path else Path.cwd()))


def lane_changes(rows: list[tuple[float, str | None, str]]) -> list[dict]:
    """`{at, from, to}` for each `(at, old, new)` row that changed lane."""
    return [{"at": at, "from": old, "to": new} for at, old, new in rows if old != new]


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


def _sqlite_tune(dbapi_connection: Any, _record: Any) -> None:  # pragma: no mutate block — sqlite3 tuning
    """Bound the -wal file and refresh the planner statistics, as each pooled connection opens.

    The server exits without disposing its pool, so a connection-close hook never runs; opening is when SQLite's own
    guidance runs `optimize`, and 0x10000 makes it look at every table, not only those this connection has touched.
    """
    dbapi_connection.execute(f"PRAGMA journal_size_limit={_WAL_SIZE_LIMIT}")
    dbapi_connection.execute("PRAGMA optimize=0x10002")


class HistoryStore:
    """The history in one database; consumer threads write and request threads read, each through its own connection.

    `machines` are the machines the page draws, which place a task's events on its path.
    """

    def __init__(self, url: str, machines: Mapping[str, dict], engine: Engine | None = None) -> None:
        self.engine = engine or (
            create_engine(url, connect_args={"timeout": _SQLITE_BUSY_TIMEOUT})
            if make_url(url).get_backend_name() == "sqlite"
            else create_engine(url)
        )
        if self.engine.dialect.name == "sqlite":
            sa_event.listen(self.engine, "connect", _sqlite_tune)
        self._machines = machines
        self._summariser = Summariser(machines)
        # the level windows read since the last summary write
        self._windows: dict[tuple[Level, float, float], RunWindow] = {}
        self._windows_lock = threading.Lock()
        self._summaries_version = 0
        # the level answers computed since the last summary write, least recently used first
        self._answers: OrderedDict[Hashable, _Answer] = OrderedDict()
        self._answer_flight = threading.Lock()
        # pragma: no mutate start — SQLite compiles the postgresql insert's ON CONFLICT alike
        self._dialect = postgresql if self.engine.dialect.name == "postgresql" else sqlite
        # pragma: no mutate end
        create_tables(self.engine)  # a reader thread of the log may be bringing the same store up at the same time
        if self.repair_lanes():
            self.rebuild_summaries()
        self.build_summaries()

    def repair_lanes(self) -> int:
        """Put the lane history right where two writers left it, as `lane_repair.plan` says: how many rows it dropped or
        rewrote, 0 for a history that is right (the usual start). The summaries then need `rebuild_summaries`."""
        c = _lane_changes.c
        with self.engine.begin() as db:
            held = select(c.id, c.event_id, c.task, c.old_status, c.new_status, c.observed_at)
            rows = [tuple(r) for r in db.execute(held)]
            rewrites, drops = lane_repair.plan(rows)
            for id_, (old, new) in rewrites.items():
                db.execute(update(_lane_changes).where(c.id == id_).values(old_status=old, new_status=new))
            if drops:
                db.execute(delete(_lane_changes).where(c.id.in_(drops)))
        return len(rewrites) + len(drops)

    def _insert(self, table: Table):
        return self._dialect.insert(table)

    @property
    def checkpoints(self) -> Checkpoints:
        """How far each reader of the log got, so a restart resumes after the last entry it recorded."""
        return Checkpoints(self.engine)

    def instance(self, name: str) -> str:
        """The id this store sends under `name`, a forwarder's cursor name: minted when the store has none, then the
        same on every call and every restart. Two processes asking at once get the one that committed first."""
        take = self._insert(_instances).values(name=name, instance=uuid.uuid4().hex).on_conflict_do_nothing()
        with self.engine.begin() as db:
            db.execute(take)
            return db.execute(select(_instances.c.instance).where(_instances.c.name == name)).scalar_one()

    def record_machine(self, entry_id: str, fields: dict, *, cursor: int | None = None) -> None:
        """Write one machine event and fold it into the summaries; one the store already holds is a no-op.

        `cursor`, the event's id in the log, is saved in the same transaction, so the store never holds an event
        its cursor has not passed or a cursor past an event it lacks, or an event its summaries lack.
        """
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
            insert = self._insert(_machine_events).values(row).on_conflict_do_nothing()
            written = db.execute(insert.returning(_machine_events.c.id)).first() is not None
            if written:
                self._summarise_event(db, row)
            if cursor is not None:
                self.checkpoints.save(machine_events.STREAM, cursor, conn=db)
        if written:
            self._summaries_changed()

    def _summaries_changed(self) -> None:
        """Forget the level windows: called once a write to the summaries has committed, so a window read after it sees the
        write and one read before it is never kept."""
        with self._windows_lock:
            self._summaries_version += 1
            self._windows.clear()
            self._answers.clear()

    def _summarise_event(self, db: Connection, row: dict) -> None:
        who = self._summariser
        if (key := who.event_key(row["machine"], row["task"], row["run"], row["event_id"])) is not None:
            step = who.event_step(key, read_case(db, key), row["event"], row["occurred_at"], row["event_id"])
            write_step(db, self._insert, key, step)

    def record_lane(
        self,
        event_id: str,
        task: str,
        status: str,
        at: float,
        *,
        cursor: int | None = None,
        event: Mapping[str, Any] | None = None,
    ) -> bool:
        """Write a task's lane change and fold it into the summaries; True when a row was written. The status is kept as
        its lane id (`In Progress` is `in_progress`). One that repeats the task's last (a reconcile) is no change, and
        neither is an event id or a move (task, lane, time) the store already holds: a second writer adds no row.

        A forwarded change (`<source>/<id>`) repeats only the last status of the same source's task: two sources may
        key a task alike. `cursor`, the entry's id in the log, is saved in the same transaction, as is the lane `event`
        (the `board:lanes` fields, under `event_id`) a change writes: both land or neither does.
        """
        with self.engine.begin() as db:
            written = self._fold_lane(db, event_id, task, status, at)
            if written and event is not None:
                insert_event(db, lane_events.STREAM, event, event_id)
            if cursor is not None:
                self.checkpoints.save(lane_events.STREAM, cursor, conn=db)
        if written:
            self._summaries_changed()
        return written

    def record_lane_entry(self, entry_id: str, fields: dict, *, cursor: int | None = None) -> bool:
        """Fold one `lane_events` entry (`fields`) into the lane history as `record_lane` does, under its log id."""
        return self.record_lane(
            fields.get("event_id") or entry_id, fields["task"], fields["lane"], float(fields["time"]), cursor=cursor
        )

    def _fold_lane(self, db: Connection, event_id: str, task: str, status: str, at: float) -> bool:
        status = lane_id(status)
        name, slash, _ = event_id.partition("/")
        source = name if slash and name else None
        last = _last_lane(db, task, source)
        if (last is not None and lane_id(last) == status) or _holds_move(db, task, source, status, at):
            return False
        change = self._insert(_lane_changes).values(
            event_id=event_id, task=task, old_status=last, new_status=status, observed_at=at
        )
        if db.execute(change.on_conflict_do_nothing().returning(_lane_changes.c.id)).first() is None:
            return False
        self._summarise_lane(db, event_id, task, status, at)
        return True

    def _summarise_lane(self, db: Connection, event_id: str, task: str, status: str, at: float) -> None:
        who = self._summariser
        key = who.lane_key(task, event_id)
        if (step := who.lane_step(read_case(db, key), status, at, event_id)) is not None:
            write_step(db, self._insert, key, step)
        write_lane(db, self._insert, event_id, task, status, at)

    def import_lanes(self, changes: Iterable[Change]) -> int:
        """Add the lane changes of an earlier history, each once: how many of them the store holds that it did not.

        A change is written as the board's own event id names it, so one the store holds is not written again, and a
        move the store holds under another id (task, lane, time) or a change into the lane its task was already in
        adds nothing. Changes may be older than the rows the store holds, so each row is written unchained and the
        store's lane history is then repaired (`repair_lanes`) and its summaries rebuilt, as a start does: nothing may
        record while it runs.
        """
        ordered = sorted(changes, key=lambda change: change.at)
        ids = [change.event_id for change in ordered]
        last: dict[str, str] = {}
        with self.engine.begin() as db:
            held = _held_ids(db, ids)
            for event_id, task, lane, at in ordered:
                status = lane_id(lane)
                if last.get(task) == status:
                    continue
                last[task] = status
                name, slash, _ = event_id.partition("/")
                if _holds_move(db, task, name if slash and name else None, status, at):
                    continue
                row = {"event_id": event_id, "task": task, "old_status": None, "new_status": status, "observed_at": at}
                db.execute(self._insert(_lane_changes).values(row).on_conflict_do_nothing())
        self.repair_lanes()
        self.rebuild_summaries()
        with self.engine.connect() as db:
            return len(_held_ids(db, ids) - held)

    def build_summaries(self) -> None:
        """Build the summaries from the raw rows when they are empty or were folded under other machines: the start-up
        pass for a store that predates them or opens under an edited machine.

        Summaries that hold rows under the machines this store opened with are left as they are, so a second call
        changes nothing, except that lane counts a store lacks (its intervals predate them) are counted from the
        intervals; `rebuild_summaries` replaces them.
        """
        with self.engine.begin() as db:
            held = {table: db.execute(select(table).limit(1)).first() is not None for table in SUMMARY_TABLES}
            if held[lane_intervals] and not held[lanes]:
                count_lanes(db)
            folded_under = db.execute(select(summary_basis.c.fingerprint)).scalar()
        if folded_under != self._summariser.fingerprint() or not any(held.values()):
            self.rebuild_summaries()

    def rebuild_summaries(self) -> None:
        """Replace the summaries with ones folded from the raw rows under the machines this store holds: the machine
        events, then the lane changes, each in the order it was recorded, through the fold a write takes.

        The rows are folded in memory while writers carry on, so a large history holds no lock for its length. The write
        lock is then taken only to swap the summaries in, after folding the rows recorded since the fold read them, so
        the swap lasts as long as writing the summaries, and no row recorded meanwhile is missing from them.
        """
        fold = Fold(self._summariser)
        with self.engine.connect() as db:
            seen = self._fold_rows(db, fold, (0, 0))
        with self.engine.begin() as db:
            for table in (*SUMMARY_TABLES, summary_basis):
                db.execute(delete(table))  # the first write takes the lock, so the rows read next are the last
            self._fold_rows(db, fold, seen)
            fold.write(db)
            db.execute(insert(summary_basis).values(fingerprint=self._summariser.fingerprint()))
        self._summaries_changed()

    @staticmethod
    def _fold_rows(db: Connection, fold: Fold, after: tuple[int, int]) -> tuple[int, int]:
        """Fold the machine events and lane changes recorded past the ids `after`; the ids of the last it folded."""
        e, c = _machine_events.c, _lane_changes.c
        events = select(e.id, e.event_id, e.task, e.run, e.machine, e.event, e.occurred_at).order_by(e.id)
        changes = select(c.id, c.event_id, c.task, c.new_status, c.observed_at).order_by(c.id)
        last_event, last_change = after
        for row in _in_id_order(db, events, e.id, last_event):
            fold.event(row)
            last_event = row["id"]
        for row in _in_id_order(db, changes, c.id, last_change):
            fold.lane(row["event_id"], row["task"], row["new_status"], row["observed_at"])
            last_change = row["id"]
        return last_event, last_change

    def criteria_met(self) -> dict[str, float]:
        """When each task's Start Criteria were first seen all met, by task."""
        with self.engine.connect() as db:
            return dict(db.execute(select(_criteria_met.c.task, _criteria_met.c.met_at)).all())

    def save_criteria_met(self, met: dict[str, float]) -> None:
        """Keep `met` as the whole set: a task it leaves out is forgotten, so its next met moment is a new one."""
        with self.engine.begin() as db:
            db.execute(_criteria_met.delete())
            if met:
                db.execute(self._insert(_criteria_met), [{"task": task, "met_at": at} for task, at in met.items()])

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

    def health_stays(self, machine: dict, *, start: float, now: float, stuck_s: float) -> LaneStays:
        """The lane stays the Board `machine`'s health between `start` and `now` reads, from the lane summaries.

        The database folds the stays that ended at or after `start` into one `Dwell` per lane, counts the stays that
        began in the window per lane and folds the stays still going in a state that is not final into one `Dwell`
        per lane, so what comes back is a row per lane plus the stays still going in a state that is neither initial
        nor final for `stuck_s` or nearly: it grows with the lanes and the tasks stuck, not with the stays the window
        holds or the tasks in flight; the tasks in each lane now and every lane recorded come from the lane counts.
        """
        i = lane_intervals.c
        live = [lane for state in machine["states"] if not state["final"] for lane in (state["name"], state["id"])]
        watched = [
            lane
            for state in machine["states"]
            if not (state["final"] or state["initial"])
            for lane in (state["name"], state["id"])
        ]
        length = i.left_at - i.entered_at
        # a second of slack, so the reader's own `now - began >= stuck_s` decides a stay at the threshold
        stuck = (
            select(i.task, i.lane, i.entered_at)
            .where(i.left_at.is_(None), i.lane.in_(watched), i.entered_at < now - stuck_s + 1.0)
            .order_by(i.entered_at, i.id)
        )
        held = select(lanes.c.lane, func.sum(lanes.c.open_tasks)).group_by(lanes.c.lane).order_by(lanes.c.lane)
        with self.engine.connect() as db:
            counts = dict(db.execute(held).all())
            # Every lane a stay was in is counted, so naming them lets ended seek each lane's stays in the window.
            recorded = i.lane.in_(list(counts))
            ended = select(i.lane, func.count(), func.sum(length), func.max(length)).where(recorded, i.left_at >= start)
            # Keep the lane predicate off entered: with it SQLite satisfies GROUP BY from the stay index by scanning
            # every stay in each lane; the time range alone seeks the entered-at index and groups only the window.
            entered = select(i.lane, func.count()).where(i.entered_at.between(start, now))
            going = select(i.lane, func.count(), func.sum(now - i.entered_at), func.min(i.entered_at)).where(
                i.lane.in_(live), i.left_at.is_(None)
            )
            dwell = {lane: Dwell(n, total, longest) for lane, n, total, longest in db.execute(ended.group_by(i.lane))}
            open_dwell = {
                lane: Dwell(n, total, now - first) for lane, n, total, first in db.execute(going.group_by(i.lane))
            }
            return LaneStays(
                dwell,
                dict(db.execute(entered.group_by(i.lane)).all()),
                open_dwell,
                [Stay(task, lane, began, None) for task, lane, began in db.execute(stuck)],
                counts,
                list(counts),
            )

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

    def current_lanes(self) -> list[tuple[str, str, str, float]]:
        """`(event_id, task, lane, at)` for the latest lane change of each task, in the order those changes happened.

        The latest is picked in SQL on the task index, so a superseded change is never read."""
        c, earlier = _lane_changes.c, _lane_changes.alias("earlier")
        latest = (
            select(earlier.c.id)
            .where(earlier.c.task == c.task)
            .order_by(earlier.c.observed_at.desc(), earlier.c.id.desc())
            .limit(1)
            .correlate(_lane_changes)
            .scalar_subquery()
        )
        query = select(c.event_id, c.task, c.new_status, c.observed_at).where(c.id == latest).order_by(*_LANE_ORDER)
        return self._read(query)

    def level_runs(self, flow: str) -> list[Run]:
        """Every task's trajectory on `flow` as a `Run` of the source its event ids name, for the level's aggregates.

        The Board's trajectories are its lane changes, each lane read as the state of that name or id (a lane that is
        no state is skipped); another machine's are its events placed as `machine_steps` places them. A source is the
        `<source>/` an event id carries, which is how the hub namespaces a forwarded event; an id with none is no
        forwarder's and its run is `UNATTRIBUTED`. A run is one source's one task.
        """
        machine = self._machines[flow]
        if flow == "board":
            states = {key: state["id"] for state in machine["states"] for key in (state["name"], state["id"])}
            c = _lane_changes.c
            query = select(c.event_id, c.task, c.observed_at, c.new_status).order_by(*_LANE_ORDER)
            rows = [(event_id, task, at, states.get(lane)) for event_id, task, at, lane in self._read(query)]
        else:
            table, current = Transitions(machine), {}
            c = _machine_events.c
            query = (
                select(c.event_id, c.task, c.occurred_at, c.event)
                .where(c.machine == flow, c.task.is_not(None))
                .order_by(*_STEP_ORDER)
            )
            rows = []
            for event_id, task, at, event in self._read(query):
                key = (source(event_id), task)
                current[key] = table.target(current.get(key), event) or current.get(key, table.initial)
                rows.append((event_id, task, at, current[key]))
        steps: dict[tuple[str, str], list[tuple[float, str]]] = {}
        for event_id, task, at, state in rows:
            if state is not None:
                steps.setdefault((source(event_id), task), []).append((at, state))
        return [Run(source, task, tuple(path)) for (source, task), path in steps.items()]

    def level_window(self, level: Level, *, now: float, window_s: float) -> RunWindow:
        """The runs the level's numbers over the last `window_s` seconds up to `now` need, from the lane summaries.

        The Board's are every task that changed lane in the window or the trailing 12 weeks (aging reads those) and
        every task still waiting or working, each with its whole trajectory; the history's start and its sources come
        from the lane counts. The read grows with that activity and the tasks in flight, not with the history. Another
        machine's trajectories are its events, which are read whole (`level_runs`).
        """
        if level.machine != BOARD:
            return RunWindow(self.level_runs(level.machine))
        # The window holds every run that moved since a cutoff `now` sets, and a cutoff earlier than a request needs only
        # adds runs the level's numbers clip away, so one read at the start of the minute answers every request in it.
        bucket = now - now % _WINDOW_BUCKET_S
        key = (level, window_s, bucket)
        with self._windows_lock:
            version, held = self._summaries_version, self._windows.get(key)
        if held is None:
            held = self._read_level_window(level, now=bucket, window_s=window_s)
            with self._windows_lock:
                if self._summaries_version == version:  # a write that committed meanwhile may be missing from it
                    if len(self._windows) >= _WINDOWS_KEPT:
                        del self._windows[next(iter(self._windows))]
                    self._windows[key] = held
        return held

    def level_answer(self, level: Level, key: Hashable, *, now: float, compute: Callable[[], _Answer]) -> _Answer:
        """`compute()` for `key`, or the answer an earlier request computed in the same few seconds, as long as no
        summary has been written since.

        Only the Board's level is kept: another machine's runs are its events, which this store does not version. The
        answer is as old as the first request of its bucket, and a request that finds one being computed waits for it
        rather than computing it again.
        """
        if level.machine != BOARD:
            return compute()
        key = (level, key, now - now % _ANSWER_BUCKET_S)
        with self._answer_flight:
            with self._windows_lock:
                version, held = self._summaries_version, self._answers.get(key)
                if held is not None:
                    self._answers.move_to_end(key)
            if held is None:
                held = compute()
                with self._windows_lock:
                    if self._summaries_version == version:  # a write that committed meanwhile may be missing from it
                        self._answers[key] = held
                        if len(self._answers) > _ANSWERS_KEPT:
                            self._answers.popitem(last=False)
        return held

    def _read_level_window(self, level: Level, *, now: float, window_s: float) -> RunWindow:
        machine = self._machines[BOARD]
        states = {key: state["id"] for state in machine["states"] for key in (state["name"], state["id"])}
        _, working, waiting = state_roles(level, machine)
        i, c, n = lane_intervals.c, cases.c, lanes.c
        with self.engine.connect() as db:
            # no DISTINCT: it would send SQLite down the whole task index instead of the range of recent entries
            moved = (
                db.execute(select(i.task).where(i.entered_at >= min(now - window_s, now - AGING_WINDOW_S)))
                .scalars()
                .all()
            )
            live = (
                db.execute(select(c.case_id).where(c.machine == BOARD, c.state.in_([*waiting, *working])))
                .scalars()
                .all()
            )
            tasks = sorted({*moved, *live})
            # by task, then time, then the order they were recorded in: the task index hands them over in that order
            query = select(i.entered_at, i.source, i.task, i.lane).order_by(i.task, i.entered_at, i.id)
            rows = [
                row
                for start in range(0, len(tasks), _TASKS_PER_QUERY)
                for row in db.execute(query.where(i.task.in_(tasks[start : start + _TASKS_PER_QUERY]))).all()
            ]
            seen = db.execute(
                select(n.source, func.min(n.first_at)).where(n.lane.in_(list(states))).group_by(n.source)
            ).all()
        steps: dict[tuple[str, str], list[tuple[float, str]]] = {}
        for at, who, task, lane in rows:
            if (state := states.get(lane)) is not None:
                key = (who, task)
                if (path := steps.get(key)) is None:
                    path = steps[key] = []
                path.append((at, state))
        runs = [Run(who, task, tuple(path)) for (who, task), path in steps.items()]
        return RunWindow(runs, min((first for _, first in seen), default=None), sorted(who for who, _ in seen))

    def _read(self, query):
        with self.engine.connect() as db:
            return [tuple(row) for row in db.execute(query).all()]

    def lane_path(self, task: str) -> list[dict]:
        """`{at, from, to}` for each time the task changed lane, oldest first; a task never seen has none."""
        c = _lane_changes.c
        with self.engine.connect() as db:
            rows = db.execute(
                select(c.observed_at, c.old_status, c.new_status).where(c.task == task).order_by(*_LANE_ORDER)
            ).all()
        return lane_changes([tuple(row) for row in rows])

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


def record_machine_events(
    store: HistoryStore, log: EventLog, stop: threading.Event, *, interval: float = DEFAULT_POLL_INTERVAL
) -> None:
    """Copy the log's machine events into `store` until `stop`, resuming after the cursor the store holds.

    A store with no cursor replays what the log retains. Each entry is written with its cursor in one transaction,
    so a restart neither skips nor repeats one, and rows pruned unread are a gap (`Tail`). A database that cannot be
    reached is the sink down, not the entry bad, so the entry is read again on the next poll.
    """
    stream = machine_events.STREAM
    while not stop.is_set():
        try:
            after = store.checkpoints.load(stream)[0]
            break
        except OperationalError as exc:
            logger.warning("history: cannot read the %s cursor, retrying in %ss: %s", stream, interval, exc)
            stop.wait(interval)
    else:
        return
    log.tail(stream, after=after, interval=interval).run(
        lambda entry: store.record_machine(entry.event_id, entry.fields, cursor=entry.id),
        stop,
        transient=(OperationalError,),
    )


def record_lane_events(
    store: HistoryStore, log: EventLog, stop: threading.Event, *, interval: float = DEFAULT_POLL_INTERVAL
) -> None:
    """Fold the log's lane entries into `store`'s lane history until `stop`, resuming after the cursor the store holds.

    This is how a hub learns the lane changes its sources forward; it reads as `record_machine_events` reads, and
    each entry is written with its cursor in one transaction.
    """
    stream = lane_events.STREAM
    while not stop.is_set():
        try:
            after = store.checkpoints.load(stream)[0]
            break
        except OperationalError as exc:
            logger.warning("history: cannot read the %s cursor, retrying in %ss: %s", stream, interval, exc)
            stop.wait(interval)
    else:
        return
    log.tail(stream, after=after, interval=interval).run(
        lambda entry: store.record_lane_entry(entry.event_id, entry.fields, cursor=entry.id),
        stop,
        transient=(OperationalError,),
    )
