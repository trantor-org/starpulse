"""The board:lanes stream contract: one entry per task lane change.

A board write that moves a task records the change when it is written, under the request's actor
(`HistoryStore.record_lane`, one transaction); `BoardFeed` records the change of any other placement (a file edited by
hand, a board adapter whose writer does not say the lane it set) as `external`. Both use the
`<task>@<lane>@<entered>` event id, and a lane the history already holds is no change, so the log, the history and a hub
that folds the entry agree on one entry per change.
An entry carries `task`, `lane` (the Board machine state id) and `time` (epoch seconds when the task entered the lane),
the task's facets `team`, `milestone` and `labels` (absent when empty; a change recorded at write time carries none),
`profile` when the task has one and `actor` (`operator`, `agent`, `anonymous`, `<instance>/<workflow>`,
`starpulse/task-actor` or `external`), with the `session` and `harness` the write named. It never carries a title, a
description or a holder.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starpulse.contracts import BoardTask
    from starpulse._internal.eventlog.event_log import Entry, EventLog

STREAM = "board:lanes"
#: The actor of a change no write of the server recorded: the feed placed a lane nobody wrote through it.
EXTERNAL_ACTOR = "external"
#: The lane an archived task enters: its file keeps its status, so only the folder it sits in says it was archived.
ARCHIVED = "archived"
#: The lane a swept task enters where the Board has it: its file keeps the done status in the folder it was swept to.
COMPLETED = "completed"
UNATTRIBUTED_METRIC = "starpulse_board_lane_unattributed_total"
UNATTRIBUTED_HELP = "Lane entries appended to board:lanes since start that name no actor."


def entry(task: BoardTask, at: float, actor: str = "", session: str = "", harness: str = "") -> dict[str, Any]:
    """The entry's fields for `task` entering its lane at epoch `at`; a facet, profile, actor, session or harness it
    lacks is absent."""
    fields: dict[str, Any] = {"task": task.id, "lane": task.lane, "time": at, "team": task.team}
    if task.milestone:
        fields["milestone"] = task.milestone
    if task.labels:
        fields["labels"] = list(task.labels)
    if task.profile:
        fields["profile"] = task.profile
    for name, value in (("actor", actor), ("session", session), ("harness", harness)):
        if value:
            fields[name] = value
    return fields


def change(task: str, lane: str, at: float, actor: str = "", session: str = "", harness: str = "") -> dict[str, Any]:
    """The fields of a lane entry of only the task, the lane, the time and the `actor`, `session` and `harness` where
    given."""
    named = {"actor": actor, "session": session, "harness": harness}
    return {"task": task, "lane": lane, "time": at, **{name: value for name, value in named.items() if value}}


def append(log: EventLog, event_id: str, task: str, lane: str, at: float, actor: str = "") -> int | None:
    """Append a lane entry of only the task, the lane, the time and the `actor` where given to `log` under `event_id`,
    fail-open."""
    return log.append(STREAM, change(task, lane, at, actor), event_id=event_id)


class Unattributed:
    """Counts the entries appended to the stream from now on that name no actor, whichever process wrote them."""

    def __init__(self) -> None:
        self._count = 0
        self._lock = threading.Lock()

    def handle(self, entry: Entry) -> None:
        if not entry.fields.get("actor"):
            with self._lock:
                self._count += 1

    def count(self) -> int:
        with self._lock:
            return self._count

    def exposition(self) -> str:
        """Prometheus text of `count`."""
        name = UNATTRIBUTED_METRIC
        return f"# HELP {name} {UNATTRIBUTED_HELP}\n# TYPE {name} counter\n{name} {self.count()}\n"

    def follow(self, log: EventLog, stop: threading.Event) -> threading.Thread:
        """Count the entries `log` takes from now on, on a thread until `stop`."""
        tail = log.tail(STREAM, after=log.head() or 0)
        thread = threading.Thread(target=tail.run, args=(self.handle, stop), name="lane-unattributed", daemon=True)
        thread.start()
        return thread

