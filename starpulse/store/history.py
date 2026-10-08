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

import json
import logging
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

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
    delete,
    func,
    select,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import OperationalError

from starpulse import lane_events
from starpulse.analytics import LaneStays, Stay
from starpulse.domain.level import Level
from starpulse.domain.level_metrics import AGING_WINDOW_S, Run, RunWindow, state_roles
from starpulse.domain.transitions import Table as Transitions
from starpulse.settings.config import discover, load
from starpulse.store import events as machine_events
from starpulse.store.event_log import DEFAULT_POLL_INTERVAL, EventLog, Tail, create_tables
from starpulse.store.tables import gaps as _gaps
from starpulse.store.tables import metadata
from starpulse.summaries import (
    BOARD,
    SUMMARY_TABLES,
    Summaries,
    Summariser,
    cases,
    count_lanes,
    lane_intervals,
    lanes,
    read_case,
    source,
    write_lane,
    write_step,
)

__all__ = ["History", "machine_steps"]

logger = logging.getLogger(__name__)

#: How many tasks one statement asks the lane intervals for, under every dialect's limit on bound parameters.
_TASKS_PER_QUERY = 500

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
#: How far each reader of the log got, so a restart resumes after the last entry it recorded.
_cursors = Table(
    "starpulse_cursors",
    metadata,
    Column("stream", String, primary_key=True),
    Column("after_id", Integer, nullable=False),
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


class History(Protocol):
    """Where `/api/history` reads a task's paths from."""

    def lane_path(self, task: str) -> list[dict]: ...

    def machine_path(self, task: str, flow: str) -> tuple[list[dict], int]: ...


@runtime_checkable
class LaneHistory(History, Protocol):
    """A history that can list every task's lane changes: what sizes a Board state's sun."""

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

    def health_stays(self, machine: dict, *, start: float, now: float) -> LaneStays: ...


@runtime_checkable
class LevelHistory(History, Protocol):
    """A history that can also answer `/api/level`: each task's trajectory on a machine, by its reporting source."""

    def level_runs(self, flow: str) -> list[Run]: ...


@runtime_checkable
class SummarisedLevel(History, Protocol):
    """A history that keeps lane summaries, so the level reads the runs a window touches and not every lane change."""

    def level_window(self, level: Level, *, now: float, window_s: float) -> RunWindow: ...


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


class HistoryStore:
    """The history in one database; consumer threads write and request threads read, each through its own connection.

    `machines` are the machines the page draws, which place a task's events on its path.
    """

    def __init__(self, url: str, machines: Mapping[str, dict], engine: Engine | None = None) -> None:
        self.engine = engine or create_engine(url)
        self._machines = machines
        self._summariser = Summariser(machines)
        # pragma: no mutate start — SQLite compiles the postgresql insert's ON CONFLICT alike
        self._dialect = postgresql if self.engine.dialect.name == "postgresql" else sqlite
        # pragma: no mutate end
        create_tables(self.engine)  # a reader thread of the log may be creating its own at the same time
        for index in (*cases.indexes, *lane_intervals.indexes):  # create_all leaves a table that predates an index
            index.create(self.engine, checkfirst=True)
        self.build_summaries()

    def _insert(self, table: Table):
        return self._dialect.insert(table)

    def cursor(self, stream: str) -> int | None:
        """The log id of the last `stream` entry recorded, or None for a store that has recorded none."""
        with self.engine.connect() as db:
            return db.execute(select(_cursors.c.after_id).where(_cursors.c.stream == stream)).scalar()

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
            if db.execute(insert.returning(_machine_events.c.id)).first() is not None:
                self._summarise_event(db, row)
            if cursor is not None:
                self._save_cursor(db, machine_events.STREAM, cursor)

    def _summarise_event(self, db: Connection, row: dict) -> None:
        who = self._summariser
        if (key := who.event_key(row["machine"], row["task"], row["run"], row["event_id"])) is not None:
            step = who.event_step(key, read_case(db, key), row["event"], row["occurred_at"], row["event_id"])
            write_step(db, self._insert, key, step)

    def save_cursor(self, stream: str, after_id: int) -> None:
        """Keep `after_id` as the log id `stream`'s reader has passed, in place of the last one."""
        with self.engine.begin() as db:
            self._save_cursor(db, stream, after_id)

    def _save_cursor(self, db: Connection, stream: str, after_id: int) -> None:
        save = self._insert(_cursors).values(stream=stream, after_id=after_id)
        db.execute(save.on_conflict_do_update(index_elements=["stream"], set_={"after_id": save.excluded.after_id}))

    def record_lane(self, event_id: str, task: str, status: str, at: float, *, cursor: int | None = None) -> bool:
        """Write a task's lane change and fold it into the summaries; True when a row was written. A status that
        repeats the task's last one (a reconcile) is no change, and neither is an event id the store already holds.

        A forwarded change (`<source>/<id>`) repeats only the last status of the same source's task: two sources may
        key a task alike. `cursor`, the entry's id in the log, is saved in the same transaction.
        """
        with self.engine.begin() as db:
            written = self._fold_lane(db, event_id, task, status, at)
            if cursor is not None:
                self._save_cursor(db, lane_events.STREAM, cursor)
        return written

    def record_lane_entry(self, entry_id: str, fields: dict, *, cursor: int | None = None) -> bool:
        """Fold one `lane_events` entry (`fields`) into the lane history as `record_lane` does, under its log id."""
        return self.record_lane(fields.get("event_id") or entry_id, fields["task"], fields["lane"], float(fields["time"]), cursor=cursor)

    def _fold_lane(self, db: Connection, event_id: str, task: str, status: str, at: float) -> bool:
        name, slash, _ = event_id.partition("/")
        last = _last_lane(db, task, name if slash and name else None)
        if last == status:
            return False
        change = self._insert(_lane_changes).values(
            event_id=event_id, task=task, old_status=last, new_status=status, observed_at=at
        )
        if db.execute(change.on_conflict_do_nothing().returning(_lane_changes.c.id)).first() is None:
            return False
        who = self._summariser
        key = who.lane_key(task, event_id)
        if (step := who.lane_step(read_case(db, key), status, at, event_id)) is not None:
            write_step(db, self._insert, key, step)
        write_lane(db, self._insert, event_id, task, status, at)
        return True

    def build_summaries(self) -> None:
        """Build the summaries from the raw rows when they are empty: the start-up pass for a store that predates them.

        Summaries that hold any row are left as they are, so a second call changes nothing, except that lane counts a
        store lacks (its intervals predate them) are counted from the intervals; `rebuild_summaries` replaces them
        and `summary_differences` says whether they match the raw rows.
        """
        with self.engine.begin() as db:
            held = {table: db.execute(select(table).limit(1)).first() is not None for table in SUMMARY_TABLES}
            if held[lane_intervals] and not held[lanes]:
                count_lanes(db)
        if not any(held.values()):
            self.rebuild_summaries()

    def rebuild_summaries(self) -> None:
        """Replace the summaries with ones folded from the raw rows, in one transaction.

        Nothing may record while it runs: a row written meanwhile is missing from them.
        """
        with self.engine.begin() as db:
            for table in SUMMARY_TABLES:
                db.execute(delete(table))
            self._folded(db).write(db)

    def summary_differences(self) -> list[str]:
        """Each way the summaries differ from the ones folded from the raw rows, one line each; none when they match."""
        with self.engine.connect() as db:
            return self._folded(db).differences(Summaries.read(db))

    def _folded(self, db: Connection) -> Summaries:
        """The summaries the raw rows give, in the order they were recorded."""
        folded = Summaries()
        e, c = _machine_events.c, _lane_changes.c
        events = select(e.event_id, e.task, e.run, e.machine, e.event, e.occurred_at).order_by(e.id)
        for event_id, task, run, machine, event, at in db.execute(events.execution_options(yield_per=5000)):
            folded.event(self._summariser, event_id, task, run, machine, event, at)
        changes = select(c.event_id, c.task, c.new_status, c.observed_at).order_by(c.id)
        for event_id, task, lane, at in db.execute(changes.execution_options(yield_per=5000)):
            folded.lane(self._summariser, event_id, task, lane, at)
        return folded

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

    def health_stays(self, machine: dict, *, start: float, now: float) -> LaneStays:
        """The lane stays the Board `machine`'s health between `start` and `now` reads, from the lane summaries.

        Those are the stays that ended at or after `start`, those that began in the window, and the ones still going
        in a state that is not final, so the read grows with the window and the tasks in flight, not with every task
        the Board has finished; the tasks in each lane now and every lane recorded come from the lane counts.
        """
        i = lane_intervals.c
        live = [lane for state in machine["states"] if not state["final"] for lane in (state["name"], state["id"])]
        wanted = (i.entered_at.between(start, now), i.left_at >= start, i.left_at.is_(None) & i.lane.in_(live))
        columns = (i.id, i.task, i.lane, i.entered_at, i.left_at)
        with self.engine.connect() as db:
            rows = {row[0]: row for where in wanted for row in db.execute(select(*columns).where(where))}
            held = select(lanes.c.lane, func.sum(lanes.c.open_tasks)).group_by(lanes.c.lane).order_by(lanes.c.lane)
            counts = dict(db.execute(held).all())
        stays = [Stay(*row[1:]) for _, row in sorted(rows.items())]
        return LaneStays(stays, counts, list(counts))

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

    def lane_changes(self) -> list[tuple[str, str, str, float]]:
        """`(event_id, task, lane, at)` for every lane change of every task, oldest first."""
        c = _lane_changes.c
        return self._read(select(c.event_id, c.task, c.new_status, c.observed_at).order_by(*_LANE_ORDER))

    def current_lanes(self) -> list[tuple[str, str, str, float]]:
        """`(event_id, task, lane, at)` for the latest lane change of each task, in the order the tasks first moved."""
        return list({row[1]: row for row in self.lane_changes()}.values())

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
        machine = self._machines[BOARD]
        states = {key: state["id"] for state in machine["states"] for key in (state["name"], state["id"])}
        _, working, waiting = state_roles(level, machine)
        i, c, n = lane_intervals.c, cases.c, lanes.c
        with self.engine.connect() as db:
            # no DISTINCT: it would send SQLite down the whole task index instead of the range of recent entries
            moved = db.execute(
                select(i.task).where(i.entered_at >= min(now - window_s, now - AGING_WINDOW_S))
            ).scalars()
            live = db.execute(select(c.case_id).where(c.machine == BOARD, c.state.in_([*waiting, *working]))).scalars()
            tasks = sorted({*moved, *live})
            columns = (i.entered_at, i.id, i.event_id, i.task, i.lane)
            rows = [
                tuple(row)
                for start in range(0, len(tasks), _TASKS_PER_QUERY)
                for row in db.execute(select(*columns).where(i.task.in_(tasks[start : start + _TASKS_PER_QUERY]))).all()
            ]
            seen = db.execute(
                select(n.source, func.min(n.first_at)).where(n.lane.in_(list(states))).group_by(n.source)
            ).all()
        steps: dict[tuple[str, str], list[tuple[float, str]]] = {}
        for at, _, event_id, task, lane in sorted(rows):  # by time, then by the order they were recorded in
            if (state := states.get(lane)) is not None:
                steps.setdefault((source(event_id), task), []).append((at, state))
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
        """The task's events on `flow` as `{at, event, state}` in order, and their count."""
        c = _machine_events.c
        with self.engine.connect() as db:
            rows = db.execute(
                select(c.occurred_at, c.event).where(c.task == task, c.machine == flow).order_by(*_STEP_ORDER)
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
            after = store.cursor(stream)
            break
        except OperationalError as exc:
            logger.warning("history: cannot read the %s cursor, retrying in %ss: %s", stream, interval, exc)
            stop.wait(interval)
    else:
        return
    Tail(log, stream, after=after, interval=interval).run(
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
            after = store.cursor(stream)
            break
        except OperationalError as exc:
            logger.warning("history: cannot read the %s cursor, retrying in %ss: %s", stream, interval, exc)
            stop.wait(interval)
    else:
        return
    Tail(log, stream, after=after, interval=interval).run(
        lambda entry: store.record_lane_entry(entry.event_id, entry.fields, cursor=entry.id),
        stop,
        transient=(OperationalError,),
    )
