"""The config blocks the scheduler worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from starpulse._internal.config.config import Config


def scheduler_fixed_blocks(config: Config) -> tuple:
    """What of `config` the worker's board and history database were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board)


def scheduler_live_blocks(config: Config) -> tuple:
    """What of `config` the runtime is built from; a change to anything else needs no rebuild."""
    return (config.scheduler, config.level, config.session_start_url)
