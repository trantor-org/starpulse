"""Follows the `runs:resync` entries the sweeper's `runs` kind writes, so an adapter lists its source again."""

import logging
import threading
from collections.abc import Callable
from typing import Any

from starpulse.event_log.event_log import EventLog, Tail
from starpulse.event_log.wake import StopEvent
from starpulse.runs.model.run_events import RESYNC

logger = logging.getLogger(__name__)

#: How long a relist holds the next one back, in seconds: a burst of status posts or run events lists the source once
#: more, not once each; a relist reads the whole source, so the entries it waited out leave nothing unread.
RELIST_GAP = 10.0


def follow_resync(
    log: EventLog, instance: str, relist: Callable[[], object], stop: StopEvent, gap: float = RELIST_GAP
) -> None:
    """Call `relist` once for each batch of `RESYNC` entries naming `instance`, then wait `gap`; the entries that arrive
    meanwhile fold into the next call, and a failed call asks again. Runs on a thread until `stop`; entries before this call are not read."""
    tail = Tail.live(log, RESYNC)
    asked = False

    def on_entry(entry: Any) -> None:
        nonlocal asked
        asked = asked or entry.fields.get("instance") == instance

    def after_batch() -> None:
        nonlocal asked
        if not asked:
            return
        asked = False
        try:
            relist()
        except Exception:  # a relist's bug must not stop the follower
            logger.exception("resync %s: relist failed", instance)
            log.publish(RESYNC, {"instance": instance})  # asks again, held back by the gap below
        stop.wait(gap)  # adr-exempt: debounce

    threading.Thread(
        target=tail.run, args=(on_entry, stop), kwargs={"after_batch": after_batch}, name=f"{instance}-resync", daemon=True
    ).start()
