"""What the history store keeps on write, so a read of flow health or the level need not fold every row.

Three summaries follow the raw rows, updated in the transaction that writes one:

- `starpulse_step_summaries`: per UTC day, machine, from-state and to-state, how many steps were taken and the seconds
  spent in the from-state before them. The dwell in a state is the duration of the steps leaving it.
- `starpulse_cases`: each case's current state, when it entered it, when it was first seen and its last event. A
  case is one source's one task or run on one machine; the Board is the machine `board`, its steps its lane changes.
- `starpulse_lane_intervals`: each stay of a task in a lane, `left_at` null while it is still there. The lane is the
  Board's status as recorded, so a lane the Board machine lacks is kept for health to name.

Rows are folded in the order the store recorded them, not by their time, so a late event counts as a step of zero
length and leaves its case where the latest recorded event put it. An event the store cannot attribute is not
summarised: one of a machine the page does not draw, one with neither a task nor a run, or a lane the Board machine
lacks (its interval is kept all the same). `Summaries` is the same fold held in memory, which rebuilds the tables and
which `HistoryStore.summary_differences` compares them with.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
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

from starpulse.domain.level_metrics import UNATTRIBUTED
from starpulse.machine_tasks import tables as transitions
from starpulse.store.tables import metadata

BOARD = "board"
#: How many differences of one summary a consistency check lists before it counts the rest.
_LISTED = 20
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
    Index("ix_starpulse_lane_intervals_task", "task", "left_at"),
    Index("ix_starpulse_lane_intervals_entered", "entered_at"),
    Index("ix_starpulse_lane_intervals_left", "left_at"),
)
SUMMARY_TABLES = (step_summaries, cases, lane_intervals)

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


def write_lane(db: Connection, event_id: str, task: str, lane: str, at: float) -> None:
    """End the task's open stay at `at` and begin its stay in `lane`."""
    i = lane_intervals.c
    db.execute(
        update(lane_intervals)
        .where(i.task == task, i.left_at.is_(None))
        .values(left_at=case((i.entered_at > at, i.entered_at), else_=at))
    )
    db.execute(insert(lane_intervals).values(task=task, lane=lane, entered_at=at, event_id=event_id))


@dataclass
class Summaries:
    """The three summaries in memory, folded from raw rows in the order given."""

    #: (day, machine, from, to) -> [steps, seconds]
    steps: dict[tuple, list] = field(default_factory=dict)
    cases: dict[Key, Case] = field(default_factory=dict)
    #: lane-change event id -> (task, lane, entered, left)
    intervals: dict[str, tuple] = field(default_factory=dict)
    _open: dict[str, str] = field(default_factory=dict)

    def event(
        self, who: Summariser, event_id: str, task: str | None, run: str | None, machine: str, event: str, at: float
    ):
        if (key := who.event_key(machine, task, run, event_id)) is not None:
            self._step(key, who.event_step(key, self.cases.get(key), event, at, event_id))

    def lane(self, who: Summariser, event_id: str, task: str, lane: str, at: float) -> None:
        key = who.lane_key(task, event_id)
        if (step := who.lane_step(self.cases.get(key), lane, at, event_id)) is not None:
            self._step(key, step)
        if (open_id := self._open.get(task)) is not None:
            prior = self.intervals[open_id]
            self.intervals[open_id] = (*prior[:3], max(at, prior[2]))
        self.intervals[event_id] = (task, lane, at, None)
        self._open[task] = event_id

    def _step(self, key: Key, step: Step) -> None:
        total = self.steps.setdefault((step.day, key[0], step.from_state, step.to_state), [0, 0.0])
        total[0] += 1
        total[1] += step.duration
        self.cases[key] = step.case

    def write(self, db: Connection) -> None:
        """Insert every row; the tables are empty."""
        rows = {
            step_summaries: [
                {"day": d, "machine": m, "from_state": f, "to_state": t, "steps": n, "duration_s": s}
                for (d, m, f, t), (n, s) in self.steps.items()
            ],
            cases: [
                dict(machine=m, source=src, kind=k, case_id=c, **case._asdict())
                for (m, src, k, c), case in self.cases.items()
            ],
            lane_intervals: [
                {"task": t, "lane": lane, "entered_at": a, "left_at": b, "event_id": e}
                for e, (t, lane, a, b) in self.intervals.items()
            ],
        }
        for table, values in rows.items():
            for start in range(0, len(values), _CHUNK):
                db.execute(insert(table), values[start : start + _CHUNK])

    @classmethod
    def read(cls, db: Connection) -> Summaries:
        found = cls()
        s, c, i = step_summaries.c, cases.c, lane_intervals.c
        for day, machine, from_state, to_state, n, seconds in db.execute(
            select(s.day, s.machine, s.from_state, s.to_state, s.steps, s.duration_s)
        ):
            found.steps[(day, machine, from_state, to_state)] = [n, seconds]
        for machine, src, kind, case_id, *state in db.execute(
            select(c.machine, c.source, c.kind, c.case_id, c.state, c.since, c.first_at, c.last_event_id, c.last_at)
        ):
            found.cases[(machine, src, kind, case_id)] = Case(*state)
        for task, lane, entered, left, event_id in db.execute(
            select(i.task, i.lane, i.entered_at, i.left_at, i.event_id)
        ):
            found.intervals[event_id] = (task, lane, entered, left)
        return found

    def differences(self, found: Summaries) -> list[str]:
        """What `found` lacks, adds or holds differently from these summaries, one line each, a table at a time."""
        return [
            *_compare(
                "starpulse_step_summaries",
                {k: tuple(v) for k, v in self.steps.items()},
                {k: tuple(v) for k, v in found.steps.items()},
            ),
            *_compare("starpulse_cases", self.cases, found.cases),
            *_compare("starpulse_lane_intervals", self.intervals, found.intervals),
        ]


def _same(a: object, b: object) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, abs_tol=1e-6)
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(map(_same, a, b))
    return a == b


def _compare(table: str, expected: Mapping, found: Mapping) -> list[str]:
    lines = []
    for key in sorted({*expected, *found}, key=repr):
        if key not in found:
            lines.append(f"{table}: {key} is missing, expected {expected[key]}")
        elif key not in expected:
            lines.append(f"{table}: {key} is not in the raw rows, found {found[key]}")
        elif not _same(tuple(expected[key]), tuple(found[key])):
            lines.append(f"{table}: {key} expected {expected[key]}, found {found[key]}")
    if len(lines) > _LISTED:
        lines[_LISTED:] = [f"{table}: and {len(lines) - _LISTED} more"]
    return lines
