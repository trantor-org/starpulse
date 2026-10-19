"""The Forwarding context's seam with `serve`: what the forwarder last did, kept in the event log.

`starpulse worker forwarding` runs the forwarder, so `serve` never sees a batch go out. A `Publisher` keeps what the
forwarder learned of the hub (the last acknowledged send, why a batch failed, whether the hub refused the opt-in) as one
log setting and announces each change on a stream; `serve` adopts that setting (`Reported`) into its own forwarder, which
reads the cursor and the opt-in from the same log and store, and draws the status the page shows. A new `serve` or worker
process reads the setting, so neither restart blanks the page.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from starpulse._internal.hub.forward import Forwarder

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse._internal.eventlog.event_log import EventLog

logger = logging.getLogger(__name__)

RUNTIME = "forward.runtime"
REPORTED_STREAM = "forward:reported"
#: Seconds an idle tail waits for an append from another process.
POLL_S = 1.0


class Publisher:
    """Called after each forwarder step: writes the forwarder's runtime to the log when it changed."""

    def __init__(self, log: EventLog, forwarder: Forwarder) -> None:
        self._log = log
        self._forwarder = forwarder
        self._kept: dict | None = None

    def __call__(self) -> None:
        runtime = self._forwarder.runtime()
        if runtime == self._kept:
            return
        try:
            self._log.set_setting(RUNTIME, runtime)
        except Exception:
            logger.warning("forwarding: the runtime was not kept", exc_info=True)
            return
        self._kept = runtime
        self._log.append(REPORTED_STREAM, {})


class Reported:
    """Applies the worker's kept runtime to the serving process's forwarder."""

    def __init__(self, log: EventLog, forwarder: Forwarder, push: Callable[[], None]) -> None:
        self._log = log
        self._forwarder = forwarder
        self._push = push

    def apply(self) -> None:
        """Take the kept runtime and push the status; none kept yet, or one unreadable, leaves the forwarder as it was."""
        try:
            runtime = self._log.setting(RUNTIME)
        except Exception:
            logger.warning("forwarding: the runtime was not read", exc_info=True)
            return
        if not isinstance(runtime, dict):
            return
        self._forwarder.adopt(runtime)
        self._push()

    def follow(self, stop: threading.Event) -> threading.Thread:
        """Apply the kept runtime now, then each one announced after, on a thread until `stop`."""
        tail = self._log.tail(REPORTED_STREAM, after=self._log.head() or 0, interval=POLL_S)
        self.apply()
        thread = threading.Thread(
            target=tail.run, args=(lambda _entry: self.apply(), stop), name="forwarding-reported", daemon=True
        )
        thread.start()
        return thread
