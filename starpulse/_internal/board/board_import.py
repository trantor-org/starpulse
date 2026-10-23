"""One verified import of a board (D11): each Task becomes `TaskImported` followed by its recorded lane history as
imported `Transitioned` Events, recorded runs become observed run Events, and replaying every Task is checked against
its record.

A lane history that ends elsewhere than the record, or that a Task lacks, is a gap the old writes left: the Task is
imported as the record shows it and listed in the report's `gaps`."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from starpulse._internal.board.seam import OPERATOR
from starpulse._internal.board.task_history import KIND, WRITER, Record, seed
from starpulse._internal.readmodel.fold import replay
from starpulse._internal.store import EventStore, NewEvent

__all__ = ["Report", "import_board"]

#: A lane change as `HistoryStore.lane_changes` lists it: `(event_id, task, lane, at)`.
Lane = tuple[str, str, str, float]
#: A recorded run entry: its event id and its `runs:events` fields.
Run = tuple[str, dict[str, Any]]


@dataclass
class Report:
    """What the import did and whether every Task replays to its record."""

    tasks: int = 0
    imported: int = 0
    equal: int = 0
    differing: dict[str, list[str]] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    runs: int = 0
    runs_imported: int = 0

    @property
    def ok(self) -> bool:
        return not self.differing


def _new(kind: str, payload: dict[str, Any]) -> NewEvent:
    return NewEvent(kind, payload, OPERATOR, WRITER)


def _import_task(store: EventStore, task: str, record: Record, lanes: list[Lane], report: Report) -> None:
    """Append the Task's History unless it has one; list it when its lane history does not end at the record."""
    ends = lanes[-1][2] if lanes else None
    if ends != record.get("status"):
        report.gaps.append(task)
    if store.head(KIND, task):
        return
    first = seed(record, 0.0)
    if lanes:
        first["state"] = ""
    version = len(store.append(KIND, task, 0, [_new("TaskImported", first)], at=lanes[0][3] if lanes else None))
    previous = ""
    for _, _, lane, at in lanes:
        version += len(
            store.append(
                KIND, task, version, [_new("Transitioned", {"from": previous, "to": lane, "imported": True})], at=at
            )
        )
        previous = lane
    if lanes and ends != record.get("status"):
        move = {"from": previous, "to": record.get("status") or "", "imported": True}
        store.append(KIND, task, version, [_new("Transitioned", move)])
    report.imported += 1


def _differing(store: EventStore, task: str, record: Record) -> list[str]:
    """The Task fields whose replay differs from `record`."""
    row = replay(store.read(KIND, task))
    return [name for name, value in seed(record, 0.0).items() if row.get(name) != value]


def import_board(
    store: EventStore,
    records: Mapping[str, Record],
    lanes: Iterable[Lane],
    runs: Iterable[Run],
    record_run: Callable[[str, dict[str, Any]], bool],
) -> Report:
    """Import `records` with their `lanes` and the recorded `runs` into `store`, once each, and verify every Task.

    `record_run(event_id, fields)` appends one run entry and says whether it was new; the caller owns the runs context."""
    by_task: dict[str, list[Lane]] = defaultdict(list)
    for lane in lanes:
        by_task[lane[1]].append(lane)
    report = Report(tasks=len(records))
    for task, record in records.items():
        _import_task(store, task, record, by_task.get(task, []), report)
        if differing := _differing(store, task, record):
            report.differing[task] = differing
        else:
            report.equal += 1
    for event_id, fields in runs:
        report.runs += 1
        report.runs_imported += record_run(event_id, fields)
    return report
