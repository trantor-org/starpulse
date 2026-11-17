"""PSI triggers: the kernel wakes the sampler when CPU or memory stalls cross a threshold, so it never samples on a timer."""

import logging
import os
import select
import threading
from collections.abc import Sequence

from starpulse.event_log.wake import StopEvent

logger = logging.getLogger(__name__)

PRESSURE_FILES = ("/proc/pressure/cpu", "/proc/pressure/memory")

#: Stall `some` 300 ms of a 2 s window, the smallest window an unprivileged process may ask for.
TRIGGER = b"some 300000 2000000\0"


def watch(
    stop: StopEvent, wake: threading.Event, files: Sequence[str] = PRESSURE_FILES
) -> threading.Thread | None:
    """Set `wake` each time a trigger on `files` fires, on a daemon thread that ends with `stop`; None when the host has
    no PSI or refuses a trigger, which leaves the sampler to the events that wake it."""
    poller = select.poll()
    held = []
    ended, end = os.pipe()
    try:
        for path in files:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            held.append(fd)
            os.write(fd, TRIGGER)
            poller.register(fd, select.POLLPRI)
    except OSError as exc:
        logger.warning("StarPulse scheduler: no pressure trigger on %s: %s", path, exc)
        for fd in (*held, ended, end):
            os.close(fd)
        return None
    poller.register(ended, select.POLLIN)

    def run() -> None:
        try:
            while ended not in dict(poller.poll()):
                wake.set()
        finally:
            stop.unlisten(end_wait)
            for fd in (*held, ended, end):
                os.close(fd)

    def end_wait() -> None:
        os.write(end, b"x")

    stop.listen(end_wait)
    if stop.is_set():  # a stop set before `listen` calls nothing
        end_wait()
    thread = threading.Thread(target=run, name="scheduler-pressure", daemon=True)
    thread.start()
    return thread
