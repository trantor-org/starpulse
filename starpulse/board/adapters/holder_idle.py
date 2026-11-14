"""The event that tells a task's holder it went idle: a harness session settling on the task's branch."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from starpulse.event_log.events import STREAM as MACHINE_STREAM
from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry, EventLog

HARNESS_MACHINE = "harness"
SETTLED = "SESSION_SETTLED"


def settled_task(entry: Entry) -> str | None:
    """The task whose branch's session `entry` settles, else None."""
    fields = entry.fields
    settles = fields.get("machine") == HARNESS_MACHINE and fields.get("event") == SETTLED
    return fields.get("task") if entry.stream == MACHINE_STREAM and settles else None


def follow_holder_idle(settled: Callable[[str], None], log: EventLog, stop: StopEvent) -> threading.Thread:
    """Call `settled` with the task of each session that settles after this call, within the event's own latency."""
    from starpulse.event_log.event_log import Tail  # the server imports no database stack until a store opens

    def handle(entry: Entry) -> None:
        if task := settled_task(entry):
            settled(task)

    tail = Tail.live(log, MACHINE_STREAM, streams=[MACHINE_STREAM])
    thread = threading.Thread(target=tail.run, args=(handle, stop), name="board-holder-idle", daemon=True)
    thread.start()
    return thread
