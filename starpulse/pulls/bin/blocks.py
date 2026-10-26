"""The config blocks the pulls worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from __future__ import annotations
from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from starpulse.pulls.pins import Repo


class PullsConfig(Protocol):
    """The config section the Delivery worker reads; `runtime` loads the root config and hands it in, as no context imports it."""

    database_url: str | None
    board_type: str
    board: Mapping[str, object]
    task_actor: bool
    release: object
    repos: tuple[Repo, ...]
    pull_requests: bool
    ci: tuple[str, ...]


def pulls_fixed_blocks(config: PullsConfig) -> tuple:
    """What of `config` the worker's board and history database were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board)


def pulls_delivery_blocks(config: PullsConfig) -> tuple:
    """What of `config` the Delivery loops are built from; a change to anything else needs no rebuild."""
    return (config.task_actor, config.release, config.repos, config.pull_requests, config.ci)
