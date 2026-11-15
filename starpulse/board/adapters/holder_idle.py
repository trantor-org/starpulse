"""The events that tell a task's holder it went idle: a harness session settling on the task's branch, or another
session moving the task it parked back to In Progress."""

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from starpulse.event_log.events import STREAM as MACHINE_STREAM
from starpulse.event_log.lane_events import STREAM as LANE_STREAM
from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry, EventLog

HARNESS_MACHINE = "harness"
SETTLED = "SESSION_SETTLED"
WORKING = "in_progress"
PARKED = frozenset({"needs_attention", "waiting", "done"})  # lanes whose holder ended its turn before the move


def _task_of(entry: Entry, event: str) -> str | None:
    """The task whose branch's session `entry` reports as `event`, else None."""
    fields = entry.fields
    moved = fields.get("machine") == HARNESS_MACHINE and fields.get("event") == event
    return fields.get("task") if entry.stream == MACHINE_STREAM and moved else None


def follow_holder_idle(settled: Callable[[str], None], log: EventLog, stop: StopEvent) -> threading.Thread:
    """Call `settled` with the task of each session that settles, and of each task moved from a parked lane to In
    Progress, after this call, within the event's own latency. The mover may not be the holder, which settled when it
    parked the task and settles no more, so the move is the only event that tells it. A task parked before this call
    and moved after a server restart is not seen, because the lane map starts empty."""
    from starpulse.event_log.event_log import Tail  # the server imports no database stack until a store opens

    lanes: dict[str, str] = {}

    def handle(entry: Entry) -> None:
        if entry.stream == LANE_STREAM:
            task, lane = entry.fields.get("task", ""), entry.fields.get("lane", "")
            if lane == WORKING and lanes.get(task) in PARKED:
                settled(task)
            lanes[task] = lane
        elif task := _task_of(entry, SETTLED):
            settled(task)

    tail = Tail.live(log, MACHINE_STREAM, streams=[MACHINE_STREAM, LANE_STREAM])
    thread = threading.Thread(target=tail.run, args=(handle, stop), name="board-holder-idle", daemon=True)
    thread.start()
    return thread
