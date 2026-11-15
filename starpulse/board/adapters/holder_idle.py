"""The event that tells a task's holder it went idle: a harness session settling on the task's branch."""

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from starpulse.event_log.events import STREAM as MACHINE_STREAM
from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry, EventLog

HARNESS_MACHINE = "harness"
SETTLED = "SESSION_SETTLED"


def _task_of(entry: Entry, event: str) -> str | None:
    """The task whose branch's session `entry` reports as `event`, else None."""
    fields = entry.fields
    moved = fields.get("machine") == HARNESS_MACHINE and fields.get("event") == event
    return fields.get("task") if entry.stream == MACHINE_STREAM and moved else None


def follow_holder_idle(settled: Callable[[str], None], log: EventLog, stop: StopEvent) -> threading.Thread:
    """Call `settled` with the task of each session that settles, after this call, within the event's own latency."""
    from starpulse.event_log.event_log import Tail  # the server imports no database stack until a store opens

    def handle(entry: Entry) -> None:
        if task := _task_of(entry, SETTLED):
            settled(task)

    tail = Tail.live(log, MACHINE_STREAM, streams=[MACHINE_STREAM])
    thread = threading.Thread(target=tail.run, args=(handle, stop), name="board-holder-idle", daemon=True)
    thread.start()
    return thread
