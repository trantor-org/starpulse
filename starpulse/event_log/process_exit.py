"""A process's exit as a wake source: a pidfd on Linux, a kqueue `EVFILT_PROC` on macOS.

A watcher blocks on the descriptor until the process exits and never wakes on a timer; a process that exited before
the watch opened is readable at once, so the exit cannot be missed.
"""

from __future__ import annotations

import os
import select
import selectors


class ExitWatch:
    """A descriptor that is readable once `pid` has exited, a zombie not yet reaped included."""

    def __init__(self, pid: int) -> None:
        self._queue: select.kqueue | None = None
        try:
            if hasattr(os, "pidfd_open"):
                self._fd = os.pidfd_open(pid)
            else:
                self._queue = select.kqueue()
                note = select.kevent(
                    pid, select.KQ_FILTER_PROC, select.KQ_EV_ADD | select.KQ_EV_ONESHOT, select.KQ_NOTE_EXIT
                )
                self._queue.control([note], 0)
                self._fd = self._queue.fileno()
        except ProcessLookupError:  # gone before the watch: a pipe whose write end is closed reads at once
            self._queue = None
            self._fd, write = os.pipe()
            os.close(write)

    def fileno(self) -> int:
        return self._fd

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the process exits, or `timeout` seconds; whether it has exited."""
        with selectors.DefaultSelector() as selector:
            selector.register(self._fd, selectors.EVENT_READ)
            return bool(selector.select(timeout))

    def close(self) -> None:
        if self._queue is not None:
            self._queue.close()
        else:
            os.close(self._fd)


def exited(pid: int) -> bool:
    """Whether `pid` has exited, without waiting."""
    watch = ExitWatch(pid)
    try:
        return watch.wait(0)
    finally:
        watch.close()
