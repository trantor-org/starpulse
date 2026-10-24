"""What the history store keeps on write, so a read of flow health or the level need not fold every row.

Three summaries follow the raw rows, updated in the transaction that writes one:

- `starpulse_step_summaries`: per UTC day, machine, from-state and to-state, how many steps were taken and the seconds
  spent in the from-state before them. The dwell in a state is the duration of the steps leaving it.
- `starpulse_cases`: each case's current state, when it entered it, when it was first seen and its last event. A
  case is one source's one task or run on one machine; the Board is the machine `board`, its steps its lane changes.
- `starpulse_lane_intervals`: each stay of a task in a lane, `left_at` null while it is still there. The lane is the
  Board's status as recorded, so a lane the Board machine lacks is kept for health to name. Each stay also keeps its
  `source`, the `<source>/` its event id names, so the level groups runs without parsing every id.
- `starpulse_lanes`: each lane one source has recorded, how many of its tasks are in it now and when it first entered
  it, the count kept at zero once the last leaves. A read of how many tasks have finished, of where the history begins
  or of who reported does not count their stays.

`starpulse_summary_basis` holds the fingerprint of the machines the summaries were folded under (`Summariser.fingerprint`:
what places an event, not a label), so a store that opens under an edited machine rebuilds them: a rebuild happens
when the summaries are empty, when that fingerprint differs from the machines the store opened with (or none was
kept, as in a store that predates it), and after a repair or an import of lane history.

Rows are folded in the order the store recorded them, not by their time, so a late event counts as a step of zero
length and leaves its case where the latest recorded event put it. An event the store cannot attribute is not
summarised: one of a machine the page does not draw, one with neither a task nor a run, or a lane the Board machine
lacks (its interval is kept all the same). `HistoryStore.rebuild_summaries` folds the raw rows again
through the same steps a write takes, in memory (`Fold`) so it holds the write lock only to swap the result in.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any, NamedTuple

from sqlalchemy import (
    Column,
    Connection,
    Date,
    Float,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Table,
    case,
    insert,
    select,
    update,
)

from starpulse._internal.eventlog.level_metrics import UNATTRIBUTED
from starpulse._internal.machines.transitions import tables as transitions
from starpulse.event_log.tables import metadata

BOARD = "board"
_CHUNK = 5000

step_summaries = Table(
    "starpulse_step_summaries",
    metadata,
    Column("day", Date, nullable=False),
    Column("machine", String, nullable=False),
    Column("from_state", String, nullable=False),
    Column("to_state", String, nullable=False),
    Column("steps", Integer, nullable=False),
    Column("duration_s", Float, nullable=False),
    PrimaryKeyConstraint("day", "machine", "from_state", "to_state"),
)
cases = Table(
    "starpulse_cases",
    metadata,
    Column("machine", String, nullable=False),
    Column("source", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("case_id", String, nullable=False),
    Column("state", String, nullable=False),
    Column("since", Float, nullable=False),
    Column("first_at", Float, nullable=False),
    Column("last_event_id", String, nullable=False),
    Column("last_at", Float, nullable=False),
    PrimaryKeyConstraint("machine", "source", "kind", "case_id"),
    Index("ix_starpulse_cases_state", "machine", "state"),
)
lane_intervals = Table(
    "starpulse_lane_intervals",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task", String, nullable=False),
    Column("lane", String, nullable=False),
    Column("entered_at", Float, nullable=False),
    Column("left_at", Float),
    Column("event_id", String, nullable=False, unique=True),
    # the `<source>/` the event id carries (`source`), so the level groups runs without parsing every id
    Column("source", String),
    # a task's stays in the order the level reads them (entered_at, then the row id every index ends in): no sort
    Index("ix_starpulse_lane_intervals_task_entered", "task", "entered_at"),
    Index("ix_starpulse_lane_intervals_entered", "entered_at"),
    Index("ix_starpulse_lane_intervals_left", "left_at"),
    # each lane's stays by when they ended, with when they began: the health read seeks it lane by lane, never the table
    Index("ix_starpulse_lane_intervals_stay", "lane", "left_at", "entered_at"),
)
lanes = Table(
    "starpulse_lanes",
    metadata,
    Column("source", String, nullable=False),
    Column("lane", String, nullable=False),
    Column("open_tasks", Integer, nullable=False),
    Column("first_at", Float, nullable=False),
    PrimaryKeyConstraint("source", "lane"),
)
SUMMARY_TABLES = (step_summaries, cases, lane_intervals, lanes)
#: The machines' fingerprint the summaries were folded under: one row, written with the rebuild that folds them.
summary_basis = Table("starpulse_summary_basis", metadata, Column("fingerprint", String, primary_key=True))

#: A case: the machine, the source that reported it, `task` or `run`, and its id.
Key = tuple[str, str, str, str]


class Case(NamedTuple):
    state: str
    since: float
    first_at: float
    last_event_id: str
    last_at: float


class Step(NamedTuple):
    """One step of a case: the state it left (empty for its first), the state it reached and the seconds between."""

    day: date
    from_state: str
    to_state: str
    duration: float
    case: Case


def source(event_id: str) -> str:
    """The source an event id names (`<source>/<id>`), `UNATTRIBUTED` when it carries none."""
    name, slash, _ = event_id.partition("/")
    return name if slash and name else UNATTRIBUTED


def _advance(prev: Case | None, state: str, at: float, event_id: str) -> Step:
    day = datetime.fromtimestamp(at, UTC).date()
    if prev is None:
        return Step(day, "", state, 0.0, Case(state, at, at, event_id, at))
    since = prev.since if state == prev.state else at
    return Step(day, prev.state, state, max(at - prev.last_at, 0.0), Case(state, since, prev.first_at, event_id, at))


class Summariser:
    """Places an event or lane change on its case: the machines the page draws say which state a step reaches."""

    def __init__(self, machines: Mapping[str, dict]) -> None:
        self._tables = transitions(machines)
        board = machines.get(BOARD)
        self._lanes = {key: s["id"] for s in board["states"] for key in (s["name"], s["id"])} if board else {}

    def fingerprint(self) -> str:
        """A digest of what places an event or lane change: each drawn machine's initial and final states and moves,
        and the Board's lanes. An edit that moves no task (a label, a position) leaves it as it was."""
        placed = {
            name: {
                "initial": table.initial,
                "finals": sorted(table.finals),
                "moves": {event: {src: sorted(to) for src, to in by.items()} for event, by in table.moves.items()},
            }
            for name, table in self._tables.items()
        }
        basis = json.dumps([placed, self._lanes], sort_keys=True)
        return hashlib.sha256(basis.encode()).hexdigest()

    def event_key(self, machine: str, task: str | None, run: str | None, event_id: str) -> Key | None:
        """The case a machine event belongs to, or None when it has none or its machine is not drawn."""
        if machine not in self._tables:
            return None
        if task is not None:
            return machine, source(event_id), "task", task
        return None if run is None else (machine, source(event_id), "run", run)

    def event_step(self, key: Key, prev: Case | None, event: str, at: float, event_id: str) -> Step:
        table, before = self._tables[key[0]], prev.state if prev else None
        return _advance(prev, table.target(before, event) or before or table.initial, at, event_id)

    @staticmethod
    def lane_key(task: str, event_id: str) -> Key:
        return BOARD, source(event_id), "task", task

    def lane_step(self, prev: Case | None, lane: str, at: float, event_id: str) -> Step | None:
        """The step a lane change takes its task, or None when the Board machine has no state for the lane."""
        state = self._lanes.get(lane)
        return None if state is None else _advance(prev, state, at, event_id)


def _case_filter(key: Key) -> list:
    return [
        column == value for column, value in zip((cases.c.machine, cases.c.source, cases.c.kind, cases.c.case_id), key)
    ]


def read_case(db: Connection, key: Key) -> Case | None:
    c = cases.c
    row = db.execute(select(c.state, c.since, c.first_at, c.last_event_id, c.last_at).where(*_case_filter(key))).first()
    return None if row is None else Case(*row)


def write_step(db: Connection, upsert: Callable[[Table], Any], key: Key, step: Step) -> None:
    """Count `step` on its day and move its case. `upsert` is the dialect's `insert`, which has `on_conflict_do_update`."""
    add = upsert(step_summaries).values(
        day=step.day,
        machine=key[0],
        from_state=step.from_state,
        to_state=step.to_state,
        steps=1,
        duration_s=step.duration,
    )
    db.execute(
        add.on_conflict_do_update(
            index_elements=["day", "machine", "from_state", "to_state"],
            set_={
                "steps": step_summaries.c.steps + add.excluded.steps,
                "duration_s": step_summaries.c.duration_s + add.excluded.duration_s,
            },
        )
    )
    move = upsert(cases).values(
        machine=key[0],
        source=key[1],
        kind=key[2],
        case_id=key[3],
        state=step.case.state,
        since=step.case.since,
        first_at=step.case.first_at,
        last_event_id=step.case.last_event_id,
        last_at=step.case.last_at,
    )
    db.execute(
        move.on_conflict_do_update(
            index_elements=["machine", "source", "kind", "case_id"],
            set_={name: getattr(move.excluded, name) for name in ("state", "since", "last_event_id", "last_at")},
        )
    )


def write_lane(db: Connection, upsert: Callable[[Table], Any], event_id: str, task: str, lane: str, at: float) -> None:
    """End the task's open stay at `at` and begin its stay in `lane`, moving the task between the lanes' counts."""
    i = lane_intervals.c
    left = db.execute(
        update(lane_intervals)
        .where(i.task == task, i.left_at.is_(None))
        .values(left_at=case((i.entered_at > at, i.entered_at), else_=at))
        .returning(i.lane, i.event_id)
    ).all()
    for before, opened in left:
        db.execute(
            update(lanes)
            .where(lanes.c.source == source(opened), lanes.c.lane == before)
            .values(open_tasks=lanes.c.open_tasks - 1)
        )
    db.execute(
        insert(lane_intervals).values(task=task, lane=lane, entered_at=at, event_id=event_id, source=source(event_id))
    )
    enter = upsert(lanes).values(source=source(event_id), lane=lane, open_tasks=1, first_at=at)
    db.execute(
        enter.on_conflict_do_update(
            index_elements=["source", "lane"],
            set_={
                "open_tasks": lanes.c.open_tasks + 1,
                "first_at": case((lanes.c.first_at < at, lanes.c.first_at), else_=at),
            },
        )
    )


class Fold:
    """The summaries of the rows it is given, kept in memory: what `write_step` and `write_lane` leave in the tables for
    the same rows in the same order, so a rebuild folds a whole history without holding the write lock and writes the
    result in one short transaction."""

    def __init__(self, summariser: Summariser) -> None:
        self._summariser = summariser
        self._steps: dict[tuple[date, str, str, str], list] = {}
        self._cases: dict[Key, Case] = {}
        self._stays: list[dict] = []
        self._open: dict[str, list[dict]] = {}
        self._lanes: dict[tuple[str, str], list] = {}

    def event(self, row: Mapping[str, Any]) -> None:
        """Fold a machine event row as `HistoryStore.record_machine` does."""
        who = self._summariser
        if (key := who.event_key(row["machine"], row["task"], row["run"], row["event_id"])) is not None:
            self._step(
                key, who.event_step(key, self._cases.get(key), row["event"], row["occurred_at"], row["event_id"])
            )

    def lane(self, event_id: str, task: str, lane: str, at: float) -> None:
        """Fold a lane change as `HistoryStore.record_lane` does."""
        who = self._summariser
        key = who.lane_key(task, event_id)
        if (step := who.lane_step(self._cases.get(key), lane, at, event_id)) is not None:
            self._step(key, step)
        for stay in self._open.pop(task, []):
            stay["left_at"] = max(stay["entered_at"], at)
            self._lanes[(source(stay["event_id"]), stay["lane"])][0] -= 1
        stay = {"task": task, "lane": lane, "entered_at": at, "left_at": None, "event_id": event_id}
        stay["source"] = source(event_id)
        self._stays.append(stay)
        self._open[task] = [stay]
        count = self._lanes.setdefault((stay["source"], lane), [0, at])
        count[0] += 1
        count[1] = min(count[1], at)

    def _step(self, key: Key, step: Step) -> None:
        total = self._steps.setdefault((step.day, key[0], step.from_state, step.to_state), [0, 0.0])
        total[0] += 1
        total[1] += step.duration
        self._cases[key] = step.case

    def write(self, db: Connection) -> None:
        """Insert the summaries into the empty tables."""
        steps = [
            {"day": day, "machine": machine, "from_state": src, "to_state": dst, "steps": n, "duration_s": seconds}
            for (day, machine, src, dst), (n, seconds) in self._steps.items()
        ]
        placed = [
            {"machine": m, "source": s, "kind": k, "case_id": i, **case._asdict()}
            for (m, s, k, i), case in self._cases.items()
        ]
        counts = [
            {"source": src, "lane": lane, "open_tasks": n, "first_at": first}
            for (src, lane), (n, first) in self._lanes.items()
        ]
        for table, rows in ((step_summaries, steps), (cases, placed), (lane_intervals, self._stays), (lanes, counts)):
            for start in range(0, len(rows), _CHUNK):
                db.execute(insert(table), rows[start : start + _CHUNK])


def count_lanes(db: Connection) -> None:
    """Fill the empty lane counts from the lane intervals: per source and lane, the tasks still in it (zero when every
    one has left) and the first time one entered."""
    i = lane_intervals.c
    counted: dict[tuple[str, str], list] = {}
    for event_id, lane, entered, left in db.execute(
        select(i.event_id, i.lane, i.entered_at, i.left_at).execution_options(yield_per=5000)
    ):
        count = counted.setdefault((source(event_id), lane), [0, entered])
        count[0] += left is None
        count[1] = min(count[1], entered)
    rows = [
        {"source": src, "lane": lane, "open_tasks": open_tasks, "first_at": first}
        for (src, lane), (open_tasks, first) in counted.items()
    ]
    for start in range(0, len(rows), _CHUNK):
        db.execute(insert(lanes), rows[start : start + _CHUNK])
