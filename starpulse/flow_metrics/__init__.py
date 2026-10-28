"""The level: trajectories and analytics derived from the history, and the history a board adapter may keep."""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starpulse.flow_metrics.adapters.outbound.history import History, machine_steps

#: Each name and the module that defines it. They load on first use, so importing one submodule of the context does not
#: load the schema validator, the state-machine library or the database stack the others need.
_EXPORTS = {
    "History": ("starpulse.flow_metrics.adapters.outbound.history", "History"),
    "machine_steps": ("starpulse.flow_metrics.adapters.outbound.history", "machine_steps"),
}

__all__ = [
    "History",
    "machine_steps",
]


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attr = _EXPORTS[name]
    return getattr(importlib.import_module(module), attr)
