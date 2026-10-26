"""The config blocks the flow_metrics worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from starpulse._internal.config.config import Config


def flow_metrics_built_blocks(config: Config) -> tuple:
    """What of `config` the worker's machines, database and prune were built from at start; a change needs a restart."""
    return (
        config.database_url,
        config.board_type,
        config.board,
        config.event_log_retention_days,
        config.event_log_archive_dir,
    )
