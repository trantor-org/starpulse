"""The config blocks the runs worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from starpulse._internal.config.config import Config


def runs_built_blocks(config: Config) -> tuple:
    """What of `config` the worker's adapters, board and history database were built from at start; a
    change needs a restart."""
    return (config.runs, config.database_url, config.board_type, config.board)
