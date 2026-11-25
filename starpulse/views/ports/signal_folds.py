"""The fold rows the analytics routes read, as the queries and `Services` see them."""

from collections.abc import Iterable, Mapping
from typing import Any, Protocol


class SignalFoldReader(Protocol):
    """What `SignalFolds` gives the routes: the oldest folded signal's time, a window's fold rows and
    one task's spend folds with its cell's peers' phase rows and their labels."""

    def window(self, since: float, views: Iterable[str] = ...) -> dict[str, list[Any]]: ...

    def task_spend(
        self, task: str, since: float
    ) -> tuple[list[Any], dict[tuple[str, str], tuple[str, float]], Mapping[str, Mapping[str, Any]]] | None: ...

    def oldest(self) -> float | None: ...
