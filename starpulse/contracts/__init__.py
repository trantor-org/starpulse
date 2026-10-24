"""The contracts an adapter writes; the implementation is in `starpulse.contracts.adapters`.

The models need `pydantic`, which costs about 160 ms, so `starpulse.contracts.adapters` loads on the first name read
from it. `TaskKeys` is plain and loads here, which is what lets a board load build its keys without the models.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

from starpulse.contracts.task_keys import TaskKeys

if TYPE_CHECKING:
    from starpulse.contracts.adapters import (
        CONTRACTS,
        EVENT_STREAMS,
        SCHEMAS,
        ActiveRun,
        BoardTask,
        Dag,
        LaneEvent,
        MachineEvent,
        Move,
        Pool,
        RatingEvent,
        RecentRun,
        RunEvent,
        RunsSink,
        RunStatus,
        StartFailedError,
        Step,
    )

__all__ = [
    "CONTRACTS",
    "EVENT_STREAMS",
    "SCHEMAS",
    "ActiveRun",
    "BoardTask",
    "Dag",
    "LaneEvent",
    "RatingEvent",
    "MachineEvent",
    "Move",
    "Pool",
    "RecentRun",
    "RunEvent",
    "RunStatus",
    "RunsSink",
    "StartFailedError",
    "Step",
    "TaskKeys",
]


def __getattr__(name: str) -> Any:
    """A contract name, read off `starpulse.contracts.adapters` the first time it is asked for."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("starpulse.contracts.adapters"), name)
    globals()[name] = value
    return value
