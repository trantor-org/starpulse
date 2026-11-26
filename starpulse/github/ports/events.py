"""The ports of the `events` consumer: its queue over the inbox, the ingest it posts to, and the links from a pull request to a task."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from starpulse.github.model.delivery import Delivery

__all__ = ["Entry", "Head", "Ingest", "Links", "OpenWatch", "Queue", "Reader", "Stop", "Watch"]


@dataclass(frozen=True)
class Entry:
    """A delivery due for an attempt, with the attempts already spent on it and the time its row was saved."""

    delivery: Delivery
    attempts: int
    received_at: float = 0.0


class Stop(Protocol):
    """The signal that ends the consumer: set once, and a listener is called when it is."""

    def is_set(self) -> bool: ...

    def listen(self, callback: Callable[[], None]) -> None: ...

    def unlisten(self, callback: Callable[[], None]) -> None: ...


class Watch(Protocol):
    """A file watch: `fileno` is readable when the file may have changed, and `drain` clears it."""

    def fileno(self) -> int: ...

    def drain(self) -> None: ...

    def close(self) -> None: ...


OpenWatch = Callable[[str], Watch | None]


class Queue(Protocol):
    def claim(self, limit: int = ...) -> list[Entry]:
        """The deliveries due for an attempt, oldest first; a delivery the consumer has not seen yet is due."""
        ...

    def look(self) -> tuple[int, float | None]:
        """The newest inbox id and `due_in`, read together."""
        ...

    def due_in(self) -> float | None:
        """Seconds until the earliest pending delivery is due (0 when one is due now), or `None` with none pending."""
        ...

    def batch(self) -> AbstractContextManager[None]:
        """Hold each `complete` and `skip` made in the block, and record them in one transaction when it ends."""
        ...

    def complete(self, delivery_id: str) -> None: ...

    def skip(self, delivery_id: str, reason: str) -> None: ...

    def defer(self, delivery_id: str, error: str, until: float) -> None:
        """Leave the delivery pending, with no attempt spent, until epoch second `until`."""
        ...

    def fail(self, delivery_id: str, error: str, *, fatal: bool = False, exhausted: str = "dead") -> str:
        """Count a failed attempt and return the new status: `pending` with the next attempt after the backoff, or
        `exhausted` (`dead` or `skipped`) once the budget is spent, or `dead` at once when `fatal`."""
        ...


class Ingest(Protocol):
    def post(self, event: dict[str, Any]) -> int:
        """The HTTP status the ingest answered, or 0 when it could not be reached."""
        ...


class Links(Protocol):
    def task_for(self, repository: str, number: int) -> str | None:
        """The task with a link to the pull request, or `None`."""
        ...


@dataclass(frozen=True)
class Head:
    """An open pull request whose head is the commit a check was reported on."""

    number: int
    base: str
    draft: bool


class Reader(Protocol):
    """The GitHub reads a head's rollup makes."""

    def pulls(self, repository: str, sha: str) -> list[Head]:
        """The open pull requests whose head commit is `sha`."""
        ...

    def required(self, repository: str, base: str) -> frozenset[str]:
        """The contexts the rules of branch `base` require."""
        ...

    def results(self, repository: str, sha: str) -> dict[str, str]:
        """The state of each check posted on `sha`, by name."""
        ...
