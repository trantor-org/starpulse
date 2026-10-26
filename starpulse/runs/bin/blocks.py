"""The config blocks the runs worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from __future__ import annotations
from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from starpulse.runs.config import RunsInstance


class RunsConfig(Protocol):
    """The config section the Runs workers read; `runtime` loads the root config and hands it in, as no context imports it."""

    database_url: str | None
    board_type: str
    board: Mapping[str, object]
    runs: tuple[RunsInstance, ...]


def runs_built_blocks(config: RunsConfig) -> tuple:
    """What of `config` the worker's adapters, board and history database were built from at start; a
    change needs a restart."""
    return (config.runs, config.database_url, config.board_type, config.board)
