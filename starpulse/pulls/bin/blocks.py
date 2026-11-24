"""The config blocks the pulls worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from starpulse.pulls.model.pins import Repo


class PullsConfig(Protocol):
    """The config section the Delivery worker reads; `runtime` loads the root config and hands it in, as no context imports it."""

    database_url: str | None
    github: object | None
    board_type: str
    board: Mapping[str, object]
    task_actor: bool
    board_repo: str | None
    gitmodules: object | None
    owner_source: str
    release: object
    repos: tuple[Repo, ...]
    pull_requests: bool
    ci: tuple[str, ...]
    sequences: Mapping[str, tuple[str, ...]]
    awaits: tuple[str, ...]


def pulls_fixed_blocks(config: PullsConfig) -> tuple:
    """What of `config` the worker's board and history database were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board, config.github)


def pulls_delivery_blocks(config: PullsConfig) -> tuple:
    """What of `config` the Delivery loops are built from; a change to anything else needs no rebuild."""
    return (config.task_actor, config.board_repo, config.gitmodules, config.owner_source, config.release, config.repos, config.pull_requests, config.ci, config.sequences, config.awaits)
