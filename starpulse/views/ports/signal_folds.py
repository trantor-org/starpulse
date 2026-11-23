"""The fold rows the analytics routes read, as the queries and `Services` see them."""

from collections.abc import Iterable
from typing import Any, Protocol


class SignalFoldReader(Protocol):
    """What `SignalFolds` gives the routes: the oldest folded signal's time and a window's fold rows."""

    def window(self, since: float, views: Iterable[str] = ...) -> dict[str, list[Any]]: ...

    def oldest(self) -> float | None: ...
