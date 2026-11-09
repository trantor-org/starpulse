"""The event_log shared kernel: the event store, the event log and the read-model framework every context may import.

It imports no context. The history store, summaries and level metrics kept in the log stay in `starpulse.flow_metrics`.
The names load on first use, so importing a light module of the package loads no database stack.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry, EventLog, Tail

__all__ = [
    "Entry",
    "EventLog",
    "Tail",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        return getattr(importlib.import_module("starpulse.event_log.event_log"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
