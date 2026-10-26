"""The config blocks the board worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from __future__ import annotations
from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from starpulse.board.model.search_config import Search


class BoardConfig(Protocol):
    """The config section the Board's workers read; `runtime` loads the root config and hands it in, as no context imports it."""

    database_url: str | None
    board_type: str
    board: Mapping[str, object]
    read_model: bool
    search: Search


def search_built_blocks(config: BoardConfig) -> tuple:
    """What of `config` the worker's index and endpoint were built from at start; a change needs a restart."""
    return (config.database_url, config.search)


def board_built_blocks(config: BoardConfig) -> tuple:
    """What of `config` the worker's board, history and lane log were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board)
