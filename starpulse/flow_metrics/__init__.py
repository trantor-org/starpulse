"""The level: trajectories and analytics derived from the history, and the history store."""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starpulse.flow_metrics.adapters.outbound.history import HistoryStore, machine_steps

#: Each name and the module that defines it. They load on first use, so importing one submodule of the context does not
#: load the schema validator, the state-machine library or the database stack the others need.
_EXPORTS = {
    "HistoryStore": ("starpulse.flow_metrics.adapters.outbound.history", "HistoryStore"),
    "machine_steps": ("starpulse.flow_metrics.adapters.outbound.history", "machine_steps"),
}

__all__ = [
    "HistoryStore",
    "machine_steps",
]


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attr = _EXPORTS[name]
    return getattr(importlib.import_module(module), attr)
