"""The config blocks each server worker is built from or re-reads, in a leaf module so `closure` names them without
importing a worker."""

from starpulse._internal.config.config import Config


def api_built_blocks(config: Config) -> tuple:
    """What of `config` the page is built from at start; a change needs a new process."""
    return (config,)


def pulls_fixed_blocks(config: Config) -> tuple:
    """What of `config` the worker's board and history database were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board)


def pulls_delivery_blocks(config: Config) -> tuple:
    """What of `config` the Delivery loops are built from; a change to anything else needs no rebuild."""
    return (config.task_actor, config.release, config.repos, config.pull_requests, config.ci)


def scheduler_fixed_blocks(config: Config) -> tuple:
    """What of `config` the worker's board and history database were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board)


def scheduler_live_blocks(config: Config) -> tuple:
    """What of `config` the runtime is built from; a change to anything else needs no rebuild."""
    return (config.scheduler, config.level, config.session_start_url)


def runs_built_blocks(config: Config) -> tuple:
    """What of `config` the worker's adapters, board and history database were built from at start; a
    change needs a restart."""
    return (config.runs, config.database_url, config.board_type, config.board)


def flow_metrics_built_blocks(config: Config) -> tuple:
    """What of `config` the worker's machines, database and prune were built from at start; a change needs a restart."""
    return (
        config.database_url,
        config.board_type,
        config.board,
        config.event_log_retention_days,
        config.event_log_archive_dir,
    )


def search_built_blocks(config: Config) -> tuple:
    """What of `config` the worker's index and endpoint were built from at start; a change needs a restart."""
    return (config.database_url, config.search)


def board_built_blocks(config: Config) -> tuple:
    """What of `config` the worker's board, history and lane log were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board)
