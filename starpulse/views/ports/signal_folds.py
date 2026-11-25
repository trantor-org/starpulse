"""The fold rows the analytics routes read, as the queries and `Services` see them."""

from collections.abc import Iterable
from typing import Any, Protocol


class SignalFoldReader(Protocol):
    """What `SignalFolds` gives the routes: the oldest folded signal's time, a window's fold rows and
    one task's spend folds with its peers' phase rows."""

    def window(self, since: float, views: Iterable[str] = ...) -> dict[str, list[Any]]: ...

    def task_spend(
        self, task: str, since: float
    ) -> tuple[list[Any], dict[tuple[str, str], tuple[str, float]]] | None: ...

    def oldest(self) -> float | None: ...
