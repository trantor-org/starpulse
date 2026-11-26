"""The machine:events stream contract: one entry per lifecycle-machine event its writer caused.

A declared writer of a machine event publishes the event it fires here, keyed by the task or run it moved;
StarPulse draws each machine's tasks from this stream. Emission is fail-open (`EventLog.publish` never raises), so a
missing entry means "the writer's emit failed or the writer does not emit yet", never "the machine did not move".

Each entry carries `event_id` plus these string fields (absent when empty): `machine` (the machine's name, e.g.
`in-progress`), `event` (the machine's own event name), exactly one of `task` or `run`, `actor` (the writer that
fired it), and `time` (epoch seconds).
"""

import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starpulse.event_log.event_log import EventLog

STREAM = "machine:events"
#: Epoch seconds of 2023-01-01: an event timed before it is a fixture's `time=60.0`, not a run, so the step table refuses it.
EARLIEST_TIME = 1_672_531_200.0


def publish(
    machine: str,
    event: str,
    *,
    actor: str,
    task: str | None = None,
    run: str | None = None,
    now: float | None = None,
    event_id: str | None = None,
    data: Mapping[str, Any] | None = None,
    log: EventLog,
) -> int | None:
    """Append one entry to `log`, fail-open; returns its cursor, or None when the log refused it.

    `data` is the event's extra fields, which a subscriber's line carries.

    With an `event_id`, an entry of that id the log already holds is not appended again and its cursor is returned.

    Refuses an entry keyed by neither or both of `task` and `run`: a consumer keeps one latest state per key, so an
    unkeyed or doubly keyed move would land nowhere or twice.
    """
    if (task is None) == (run is None):
        raise ValueError(f"{machine} {event}: key an event by exactly one of task or run")
    fields: dict[str, Any] = {
        "machine": machine,
        "event": event,
        **({"task": task} if task is not None else {"run": run}),
        "actor": actor,
        "time": time.time() if now is None else now,
        **({"event_id": event_id} if event_id else {}),
        **({"data": dict(data)} if data else {}),
    }
    return log.publish(STREAM, fields)
