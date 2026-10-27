"""The scheduler's seam with `serve`: the status out, the settings and wakes across, all through the event log.

The scheduler worker (`starpulse worker scheduler`) runs the sampler and the dispatch loop; `serve` keeps the page and the
`/api/scheduler` route. Both read the operator's settings (the switch, the harness, quiet hours) from the one store, so
`serve` writes them directly and only has to wake the worker:

- the worker keeps the status it computes in the `STATUS` setting and announces each change on `STATUS_STREAM`; `serve`
  republishes it to its feed (`follow_status`), so the page strip keeps drawing it;
- a setting `serve` writes through `Remote` is announced on `WAKE_STREAM`, which the worker turns into a loop wake and a
  fresh status (`follow_wakes`);
- `Remote.served_status` is the worker's last status with the three settings read from the store now, so a `PUT` answers
  with its own change before the worker has ticked.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starpulse.board.board_feed import BoardFeed
from starpulse.scheduler.model.harness_setting import HarnessSetting
from starpulse.scheduler.model.quiet_hours import QuietHoursSetting
from starpulse.scheduler.model.toggle import Toggle
from starpulse.event_log.event_log import Entry, EventLog, Tail

logger = logging.getLogger(__name__)

STATUS = "scheduler.status"
STATUS_STREAM = "scheduler:status"
WAKE_STREAM = "scheduler:wake"
#: Seconds an idle tail waits for an append from the other process.
POLL_S = 0.5


def _follow(name: str, log: EventLog, stream: str, handle: Callable[[Entry], None], stop: threading.Event) -> None:
    tail = Tail.live(log, stream, interval=POLL_S)
    threading.Thread(target=tail.run, args=(handle, stop), name=name, daemon=True).start()


def publisher(log: EventLog, feed: BoardFeed) -> Callable[[str, dict[str, Any]], None]:
    """`wire_status`'s publisher for the worker: `status` goes to the worker's feed, is kept in the log and announced."""

    def publish(kind: str, status: dict[str, Any]) -> None:
        feed.publish(kind, status)
        try:
            log.set_setting(STATUS, status)
        except Exception:
            logger.warning("scheduler: the status was not kept", exc_info=True)
            return
        log._append(STATUS_STREAM, {})

    return publish


def _kept(log: EventLog) -> dict[str, Any]:
    try:
        status = log.setting(STATUS)
    except Exception:
        logger.warning("scheduler: the status was not read", exc_info=True)
        return {}
    return status if isinstance(status, dict) else {}


def follow_status(log: EventLog, feed: BoardFeed, stop: threading.Event) -> None:
    """Publish the worker's kept status to `feed` now, and each one it announces after, on a thread until `stop`."""

    def apply(_entry: Entry | None = None) -> None:
        if status := _kept(log):
            feed.publish("scheduler", status)

    _follow("scheduler-status", log, STATUS_STREAM, apply, stop)
    apply()


def follow_wakes(log: EventLog, wake: Callable[[], None], stop: threading.Event) -> None:
    """Call `wake` for each setting `serve` writes from now on, on a thread until `stop`."""
    _follow("scheduler-wakes", log, WAKE_STREAM, lambda _entry: wake(), stop)


class Remote:
    """`serve`'s stand-in for the scheduler `Runtime` the worker holds: the same setters and status, over the log."""

    def __init__(self, log: EventLog) -> None:
        self._log = log
        self._toggle = Toggle(log)
        self._quiet_hours = QuietHoursSetting(log)
        self._harness = HarnessSetting(log)

    def set_enabled(self, value: bool) -> None:
        self._toggle.set(value)
        self._wake()

    def set_quiet_hours(self, raw: object) -> None:
        """Keep the window (None clears it); a window `parse` refuses raises ValueError."""
        self._quiet_hours.set(raw)
        self._wake()

    def set_harness(self, raw: object) -> None:
        """Keep the harness the loop starts on; a bad name raises ValueError."""
        self._harness.set(raw)
        self._wake()

    def served_status(self) -> dict[str, Any]:
        """The worker's last status, none before it has sampled, over the settings as the store holds them now."""
        return {
            "sampledAt": None,
            "dimensions": [],
            **_kept(self._log),
            "enabled": self._toggle.get(),
            "harness": self._harness.get(),
            "quietHours": self._quiet_hours.state(),
        }

    status = served_status

    def _wake(self) -> None:
        self._log._append(WAKE_STREAM, {})
