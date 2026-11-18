"""The text a worker keeps in the event log for the Page API to relay on `/metrics`."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog


def kept[T](log: EventLog, name: str, kind: type[T]) -> Callable[[], T]:
    """The `kind` last kept under state `name`; empty before any was kept or when the log cannot be read."""

    def read() -> T:
        try:
            _, value = log.state(name)
        except Exception:
            return kind()
        return value if isinstance(value, kind) else kind()

    return read


def kept_text(log: EventLog, name: str) -> Callable[[], str]:
    """The text last kept under state `name`; empty before any was kept or when the log cannot be read."""
    return kept(log, name, str)


def kept_state(log: EventLog, name: str) -> Callable[[], dict[str, Any]]:
    """The mapping last kept under state `name`; empty before any was kept or when the log cannot be read."""
    return kept(log, name, dict)
