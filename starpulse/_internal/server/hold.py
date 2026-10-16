"""The wait a worker process ends in: `SIGTERM` stops it, `SIGHUP` reloads its config."""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable


def hold(stop: threading.Event, reload: Callable[[], None]) -> None:  # pragma: no mutate block — process boundary
    """Block until `SIGTERM`, running `reload` for each `SIGHUP`, one at a time."""
    reloads = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: (stop.set(), reloads.set()))
    signal.signal(signal.SIGHUP, lambda *_: reloads.set())
    while True:
        reloads.wait()
        reloads.clear()
        if stop.is_set():
            return
        reload()
