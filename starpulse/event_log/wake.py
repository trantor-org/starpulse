"""What ends an event-log reader's wait: stdlib only, so importing it loads no database stack."""

import threading
from collections.abc import Callable

#: How long a reader waits on a store that cannot be reached before it tries again, in seconds. It paces a retry after
#: a failure, never a read of a healthy log.
RETRY_DELAY = 1.0

#: How long the commit watch waits for a commit by another process on a platform with no file watch, in seconds: the
#: sweeper's default interval (`Sweeper.interval_s`), the longest any reader of the log is asked to be behind.
FALLBACK_WAKE_S = 3600.0


class StopEvent(threading.Event):
    """A stop event that calls its listeners when set, so a waiter blocks on its own wake and the stop together
    instead of looking at the event on a timer."""

    def __init__(self) -> None:
        super().__init__()
        self._listeners: list[Callable[[], None]] = []
        self._guard = threading.Lock()

    def listen(self, callback: Callable[[], None]) -> None:
        """Call `callback` each time the event is set, until `unlisten`. An event already set does not call it, so the
        caller checks `is_set` after listening."""
        with self._guard:
            self._listeners.append(callback)

    def unlisten(self, callback: Callable[[], None]) -> None:
        with self._guard:
            self._listeners.remove(callback)

    def set(self) -> None:
        super().set()
        with self._guard:
            listeners = list(self._listeners)
        for callback in listeners:
            callback()


def save_on_change(stop: StopEvent, changed: threading.Event, save: Callable[[], None], debounce: float) -> None:
    """Call `save` once, `debounce` seconds after `changed` is set, and once more when `stop` is set; with no change
    nothing is saved between. A change inside the window is covered by that window's save."""
    stop.listen(changed.set)
    try:
        while not stop.is_set():
            changed.wait()
            if stop.wait(debounce):
                break
            changed.clear()
            save()
    finally:
        stop.unlisten(changed.set)
    save()
