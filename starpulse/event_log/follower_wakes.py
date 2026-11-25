"""How often each log follower woke and how many of those wakes moved no events head, for `/metrics`:
`starpulse_follower_wakes_total{child,follower,head_moved}`.

A child counts in memory and keeps the text in the log's state every `PUBLISH_EVERY` wakes (never on a timer), for the
Page API to relay. A follower on a quiet wake did a pass that read nothing new."""

import threading
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from starpulse.event_log.kept_text import kept_text

if TYPE_CHECKING:  # annotation only: the event log imports this module
    from starpulse.event_log.event_log import EventLog

NAME = "starpulse_follower_wakes_total"
STATE = "follower.wakes."
PUBLISH_EVERY = 256


class Wakes:
    """The wakes of each follower thread, by whether the events head had moved since its last wake."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, bool], int] = {}
        self._total = 0

    def count(self, follower: str, head_moved: bool) -> bool:
        """Count one wake; whether the total has reached another `PUBLISH_EVERY`."""
        with self._lock:
            self._counts[follower, head_moved] = self._counts.get((follower, head_moved), 0) + 1
            self._total += 1
            return self._total % PUBLISH_EVERY == 0

    def counts(self) -> dict[tuple[str, bool], int]:
        with self._lock:
            return dict(self._counts)

    def samples(self, child: str) -> str:
        return "".join(
            f'{NAME}{{child="{child}",follower="{follower}",head_moved="{str(moved).lower()}"}} {n}\n'
            for (follower, moved), n in sorted(self.counts().items())
        )


def metrics_of(log: EventLog, children: Sequence[str]) -> Callable[[], str]:
    """The wake counts each of `children` kept, as one counter family; empty while none kept any."""
    kept = [kept_text(log, STATE + child) for child in children]

    def read() -> str:
        samples = "".join(read() for read in kept)
        return f"# HELP {NAME} Wakes of a log follower thread\n# TYPE {NAME} counter\n{samples}" if samples else ""

    return read
