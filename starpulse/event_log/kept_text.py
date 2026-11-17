"""The text a worker keeps in the event log for the Page API to relay on `/metrics`."""

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog


def kept_text(log: EventLog, name: str) -> Callable[[], str]:
    """The text last kept under state `name`; empty before any was kept or when the log cannot be read."""

    def read() -> str:
        try:
            _, text = log.state(name)
        except Exception:
            return ""
        return text if isinstance(text, str) else ""

    return read
