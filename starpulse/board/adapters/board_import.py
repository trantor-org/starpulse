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

from starpulse.board.model.seam import OPERATOR
from starpulse.board.adapters.task_history import KIND, WRITER, Record, seed
from starpulse.event_log.readmodel.fold import BrokenHistory, replay
from starpulse.event_log.store import EventStore, NewEvent

__all__ = ["Report", "import_board"]

#: A lane change as `HistoryStore.lane_changes` lists it: `(event_id, task, lane, at)`.
Lane = tuple[str, str, str, float]
#: A recorded run entry: its event id and its `runs:events` fields.
Run = tuple[str, dict[str, Any]]


@dataclass
class Report:
    """What the import did and whether every Task replays to its record; `broken` lists a Task whose History cannot replay."""

    tasks: int = 0
    imported: int = 0
    equal: int = 0
    differing: dict[str, list[str]] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    broken: list[str] = field(default_factory=list)
    reconciled: list[str] = field(default_factory=list)
    runs: int = 0
    runs_imported: int = 0

    @property
    def ok(self) -> bool:
        return not (self.differing or self.broken)


def _lane_id(name: object) -> str:
    """A lane's id, the form `HistoryStore.lane_changes` lists: `In Progress` is `in_progress`."""
    return str(name or "").lower().replace(" ", "_").replace("-", "_")


def _new(kind: str, payload: dict[str, Any]) -> NewEvent:
    return NewEvent(kind, payload, OPERATOR, WRITER)


def _reconcile(store: EventStore, task: str, record: Record, report: Report) -> None:
    """Append one `FieldsEdited` carrying what the record moved on from its History (a write the old path never
    recorded), and list the Task."""
    wanted = seed(record, 0.0)
    drifted = {name: wanted[name] for name in _differing(store, task, record)}
    if drifted:
        edit = _new("FieldsEdited", {"changes": drifted, "imported": True})
        store.append(KIND, task, len(store.read(KIND, task)), [edit])
        report.reconciled.append(task)


def _import_task(store: EventStore, task: str, record: Record, lanes: list[Lane], report: Report) -> None:
    """Append the Task's History unless it has one; list it when its lane history does not end at the record."""
    ends = lanes[-1][2] if lanes else None
    if ends is None or _lane_id(ends) != _lane_id(record.get("status")):
        report.gaps.append(task)
    if store.head(KIND, task):
        _reconcile(store, task, record, report)
        return
    first = seed(record, 0.0)
    if lanes:
        first["state"] = ""
    version = len(store.append(KIND, task, 0, [_new("TaskImported", first)], at=lanes[0][3] if lanes else None))
    previous = ""
    for index, (_, _, lane, at) in enumerate(lanes):
        if index == len(lanes) - 1 and _lane_id(lane) == _lane_id(record.get("status")):
            lane = record["status"]
        version += len(
            store.append(
                KIND, task, version, [_new("Transitioned", {"from": previous, "to": lane, "imported": True})], at=at
            )
        )
        previous = lane
    if lanes and ends is not None and _lane_id(ends) != _lane_id(record.get("status")):
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
        try:
            _import_task(store, task, record, by_task.get(task, []), report)
            differing = _differing(store, task, record)
        except BrokenHistory:
            report.broken.append(task)
            continue
        if differing:
            report.differing[task] = differing
        else:
            report.equal += 1
    for event_id, fields in runs:
        report.runs += 1
        report.runs_imported += record_run(event_id, fields)
    return report
