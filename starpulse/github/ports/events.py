"""The ports of the `events` consumer: its queue over the inbox, the ingest it posts to, and the links from a pull request to a task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from starpulse.github.model.delivery import Delivery

__all__ = ["Entry", "Head", "Ingest", "Links", "Queue", "Reader"]


@dataclass(frozen=True)
class Entry:
    """A delivery due for an attempt, with the attempts already spent on it."""

    delivery: Delivery
    attempts: int


class Queue(Protocol):
    def claim(self, limit: int = ...) -> list[Entry]:
        """The deliveries due for an attempt, oldest first; a delivery the consumer has not seen yet is due."""
        ...

    def complete(self, delivery_id: str) -> None: ...

    def skip(self, delivery_id: str, reason: str) -> None: ...

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
        """The task whose references hold the pull request, or `None`."""
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
