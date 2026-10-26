"""The config blocks the scheduler worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from __future__ import annotations
from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from starpulse.flow_metrics.level import Level
    from starpulse.scheduler.model.config import Scheduler


class SchedulerConfig(Protocol):
    """The config section the Scheduler worker reads; `runtime` loads the root config and hands it in, as no context imports it."""

    database_url: str | None
    board_type: str
    board: Mapping[str, object]
    scheduler: Scheduler
    level: Level | None
    session_start_url: str | None


def scheduler_fixed_blocks(config: SchedulerConfig) -> tuple:
    """What of `config` the worker's board and history database were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board)


def scheduler_live_blocks(config: SchedulerConfig) -> tuple:
    """What of `config` the runtime is built from; a change to anything else needs no rebuild."""
    return (config.scheduler, config.level, config.session_start_url)
