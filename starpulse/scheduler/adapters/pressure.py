"""PSI triggers: the kernel wakes the sampler when CPU or memory stalls cross a threshold, so it never samples on a timer."""

from __future__ import annotations

import logging
import os
import select
import threading
from collections.abc import Sequence

logger = logging.getLogger(__name__)

PRESSURE_FILES = ("/proc/pressure/cpu", "/proc/pressure/memory")

#: Stall `some` 300 ms of a 2 s window, the smallest window an unprivileged process may ask for.
TRIGGER = b"some 300000 2000000\0"

#: How long the watcher blocks in `poll` before it looks at `stop`, in milliseconds.
_STOP_SLICE_MS = 1000


def watch(
    stop: threading.Event, wake: threading.Event, files: Sequence[str] = PRESSURE_FILES
) -> threading.Thread | None:
    """Set `wake` each time a trigger on `files` fires, on a daemon thread that ends with `stop`; None when the host has
    no PSI or refuses a trigger, which leaves the sampler to the events that wake it."""
    poller = select.poll()
    held = []
    try:
        for path in files:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            held.append(fd)
            os.write(fd, TRIGGER)
            poller.register(fd, select.POLLPRI)
    except OSError as exc:
        logger.warning("StarPulse scheduler: no pressure trigger on %s: %s", path, exc)
        for fd in held:
            os.close(fd)
        return None

    def run() -> None:
        try:
            while not stop.is_set():
                if poller.poll(_STOP_SLICE_MS):
                    wake.set()
        finally:
            for fd in held:
                os.close(fd)

    thread = threading.Thread(target=run, name="scheduler-pressure", daemon=True)
    thread.start()
    return thread
