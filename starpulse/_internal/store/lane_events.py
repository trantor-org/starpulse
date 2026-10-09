"""The board:lanes stream contract: one entry per task lane change a Board feed applied.

`BoardFeed` appends an entry beside each lane change it records in the history (`HistoryStore.record_lane`), under
the same `<task>@<lane>@<entered>` event id, so the log, the history and a hub that folds the entry agree on one id.
An entry carries `task`, `lane` (the Board machine state id) and `time` (epoch seconds when the task entered the lane),
the task's facets `team`, `milestone` and `labels` (absent when empty), and `assignee` when the task has one. It never
carries a title, a description, a holder or any session detail. `assignee` names a person, so it leaves the instance
only while it is opted in to naming (`adapters.runs.forwarded.PERSON`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starpulse.contracts import BoardTask
    from starpulse._internal.store.event_log import EventLog
    from starpulse._internal.store.history import HistoryStore

STREAM = "board:lanes"
#: The cursor name under which a store records that its lane history has been put in the log.
REPLAYED = "board:lanes:replayed"
#: The fields a forwarded lane entry may carry.
FIELDS = ("task", "lane", "time", "team", "milestone", "labels", "assignee")


def entry(task: BoardTask, at: float) -> dict[str, Any]:
    """The entry's fields for `task` entering its lane at epoch `at`; a facet or assignee the task lacks is absent."""
    fields: dict[str, Any] = {"task": task.id, "lane": task.lane, "time": at, "team": task.team}
    if task.milestone:
        fields["milestone"] = task.milestone
    if task.labels:
        fields["labels"] = list(task.labels)
    if task.assignee:
        fields["assignee"] = task.assignee
    return fields


def publish(log: EventLog, event_id: str, task: BoardTask, at: float) -> int | None:
    """Append the lane entry for `task` to `log` under `event_id`, fail-open; an id the log holds is not appended again."""
    return log.append(STREAM, entry(task, at), event_id=event_id)


def append(log: EventLog, event_id: str, task: str, lane: str, at: float) -> int | None:
    """Append a lane entry of only the task, the lane and the time to `log` under `event_id`, fail-open."""
    return log.append(STREAM, {"task": task, "lane": lane, "time": at}, event_id=event_id)


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
