"""The config blocks the board worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from starpulse._internal.config.config import Config


def search_built_blocks(config: Config) -> tuple:
    """What of `config` the worker's index and endpoint were built from at start; a change needs a restart."""
    return (config.database_url, config.search)


def board_built_blocks(config: Config) -> tuple:
    """What of `config` the worker's board, history and lane log were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board)
