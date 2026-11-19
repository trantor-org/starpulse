"""A process descriptor per registered session: its exit, however it came, is the session's end."""

import logging
import os
import select
import threading
from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)


class ExitWatch:
    """Holds a pidfd per watched process and calls `ended(session, pid)` once when it exits, a kill or crash included."""

    def __init__(self, ended: Callable[[str, int], None]) -> None:
        self._ended = ended
        self._held: set[tuple[str, int]] = set()
        self._lock = threading.Lock()

    def watch(self, session: str, pid: int) -> bool:
        """Whether a descriptor was opened: false when this process is already watched or has already gone."""
        with self._lock:
            if (session, pid) in self._held:
                return False
            try:
                descriptor = os.pidfd_open(pid)
            except OSError:
                return False
            self._held.add((session, pid))
        threading.Thread(target=self._await, args=(session, pid, descriptor), name=f"exit-watch-{pid}", daemon=True).start()
        return True

    def _await(self, session: str, pid: int, descriptor: int) -> None:
        try:
            select.select([descriptor], [], [])
        finally:
            os.close(descriptor)
        try:
            self._ended(session, pid)
        except Exception:  # noqa: BLE001 — a failed publish never stops the other watches
            logger.exception("session %s: its end was not published", session)
        with self._lock:
            self._held.discard((session, pid))


def watch_registered(
    sessions: Iterable[str], process_of: Callable[[str], tuple[str, int] | None], watch: Callable[[str, int], bool]
) -> None:
    """Watch the process of each registered session in `sessions` that has a running one, under its local session id."""
    for session in sessions:
        if (process := process_of(session)) is not None:
            watch(*process)
