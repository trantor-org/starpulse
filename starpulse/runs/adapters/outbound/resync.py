"""Follows the `runs:resync` entries the sweeper's `runs` kind writes, so an adapter lists its source again."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from starpulse.event_log.event_log import EventLog, Tail
from starpulse.event_log.wake import StopEvent
from starpulse.runs.model.run_events import RESYNC


def follow_resync(log: EventLog, instance: str, relist: Callable[[], object], stop: StopEvent) -> None:
    """Call `relist` for each `RESYNC` entry naming `instance`, on a thread until `stop`; entries before this call are not read."""
    tail = Tail.live(log, RESYNC)

    def on_entry(entry: Any) -> None:
        if entry.fields.get("instance") == instance:
            relist()

    threading.Thread(target=tail.run, args=(on_entry, stop), name=f"{instance}-resync", daemon=True).start()
