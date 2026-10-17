"""The board:lanes stream contract: one entry per task lane change a Board feed applied.

`BoardFeed` appends an entry beside each lane change it records in the history (`HistoryStore.record_lane`), under
the same `<task>@<lane>@<entered>` event id, so the log, the history and a hub that folds the entry agree on one id.
An entry carries `task`, `lane` (the Board machine state id) and `time` (epoch seconds when the task entered the lane),
the task's facets `team`, `milestone` and `labels` (absent when empty), `assignee` when the task has one and `actor`
(`operator`, `agent`, `anonymous` or `<instance>/<workflow>`) when the move was a write the board's server judged,
with the `session` and `harness` that write named. It never carries a title, a description or a holder. `assignee` names a person, so it leaves the instance
only while it is opted in to naming (`adapters.runs.forwarded.PERSON`).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starpulse.contracts import BoardTask
    from starpulse._internal.eventlog.event_log import Entry, EventLog
    from starpulse._internal.eventlog.history import HistoryStore

STREAM = "board:lanes"
#: The cursor name under which a store records that its lane history has been put in the log.
REPLAYED = "board:lanes:replayed"
#: The fields a forwarded lane entry may carry.
FIELDS = ("task", "lane", "time", "team", "milestone", "labels", "assignee", "actor")
UNATTRIBUTED_METRIC = "starpulse_board_lane_unattributed_total"
UNATTRIBUTED_HELP = "Lane entries appended to board:lanes since start that name no actor."


def entry(task: BoardTask, at: float, actor: str = "", session: str = "", harness: str = "") -> dict[str, Any]:
    """The entry's fields for `task` entering its lane at epoch `at`; a facet, assignee, actor, session or harness it
    lacks is absent."""
    fields: dict[str, Any] = {"task": task.id, "lane": task.lane, "time": at, "team": task.team}
    if task.milestone:
        fields["milestone"] = task.milestone
    if task.labels:
        fields["labels"] = list(task.labels)
    if task.assignee:
        fields["assignee"] = task.assignee
    for name, value in (("actor", actor), ("session", session), ("harness", harness)):
        if value:
            fields[name] = value
    return fields


def publish(
    log: EventLog, event_id: str, task: BoardTask, at: float, actor: str = "", session: str = "", harness: str = ""
) -> int | None:
    """Append the lane entry for `task` to `log` under `event_id`, fail-open; an id the log holds is not appended again."""
    return log.append(STREAM, entry(task, at, actor, session, harness), event_id=event_id)


def append(log: EventLog, event_id: str, task: str, lane: str, at: float) -> int | None:
    """Append a lane entry of only the task, the lane and the time to `log` under `event_id`, fail-open."""
    return log.append(STREAM, {"task": task, "lane": lane, "time": at}, event_id=event_id)


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
        from starpulse._internal.eventlog.event_log import Tail  # noqa: PLC0415 - the database stack loads when a log opens

        tail = Tail(log, STREAM, after=log.head() or 0)
        thread = threading.Thread(target=tail.run, args=(self.handle, stop), name="lane-unattributed", daemon=True)
        thread.start()
        return thread


def replay(store: HistoryStore, log: EventLog) -> int:
    """Append every lane change `store` holds to `log`, once: how many it appended, 0 when an earlier call finished.

    The entries carry the changes' own event ids, so one the log already holds is not appended twice, and they hold
    only the task, the lane and the time: the history keeps no facets. A log that refuses an entry leaves the replay
    unfinished, and the next call goes again.
    """
    if store.cursor(REPLAYED) is not None:
        return 0
    changes = store.lane_changes()
    for event_id, task, lane, at in changes:
        if append(log, event_id, task, lane, at) is None:
            return 0
    store.save_cursor(REPLAYED, 1)
    return len(changes)
