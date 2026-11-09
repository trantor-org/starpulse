"""The fold rows the analytics routes read, as the queries and `Services` see them."""

from collections.abc import Iterable, Iterator
from typing import Any, Protocol

from starpulse.contracts.signals import Signal


class SignalFoldReader(Protocol):
    """What `SignalFolds` gives the routes: the oldest signal's time, a window's fold rows and a window's sessions."""

    def window(self, since: float, views: Iterable[str] = ...) -> dict[str, list[Any]]: ...

    def oldest(self) -> float | None: ...

    def sessions(self, since: float = 0.0) -> Iterator[list[Signal]]: ...
