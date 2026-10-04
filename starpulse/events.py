"""The machine:events stream contract: one entry per lifecycle-machine event its writer caused.

A declared writer of a machine event publishes the event it fires here, keyed by the task or run it moved;
StarPulse draws each machine's tasks from this stream. Emission is fail-open (`StreamProducer`), so a missing
entry means "the writer's emit failed or the writer does not emit yet", never "the machine did not move".

Each entry carries `event_id` plus these string fields (absent when empty): `machine` (the machine's name, e.g.
`in-progress`), `event` (the machine's own event name), exactly one of `task` or `run`, `actor` (the writer that
fired it), and `time` (epoch seconds).
"""

from __future__ import annotations

import time
from typing import Any

from starpulse.streams import StreamProducer

# Redis is reached at MACHINE_EVENTS_REDIS_HOST/_PORT plus the shared REDIS_PASSWORD.
STREAM = "machine:events"
REDIS_ENV_PREFIX = "MACHINE_EVENTS"


def publish(
    machine: str,
    event: str,
    *,
    actor: str,
    task: str | None = None,
    run: str | None = None,
    now: float | None = None,
    producer: StreamProducer | None = None,
) -> str | None:
    """Emit one entry, fail-open; returns its stream id, or None when Redis refused it.

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
    }
    return (producer or StreamProducer.from_env(REDIS_ENV_PREFIX, stream=STREAM)).emit(fields)
