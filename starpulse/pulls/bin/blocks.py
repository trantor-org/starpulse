"""The config blocks the pulls worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from starpulse._internal.config.config import Config


def pulls_fixed_blocks(config: Config) -> tuple:
    """What of `config` the worker's board and history database were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board)


def pulls_delivery_blocks(config: Config) -> tuple:
    """What of `config` the Delivery loops are built from; a change to anything else needs no rebuild."""
    return (config.task_actor, config.release, config.repos, config.pull_requests, config.ci)
