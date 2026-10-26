"""The config blocks the flow_metrics worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from __future__ import annotations
from collections.abc import Mapping
from typing import Protocol


class FlowMetricsConfig(Protocol):
    """The config section the flow_metrics worker reads; `runtime` loads the root config and hands it in, as no context imports it."""

    database_url: str | None
    board_type: str
    board: Mapping[str, object]
    event_log_retention_days: int
    event_log_archive_dir: str


def flow_metrics_built_blocks(config: FlowMetricsConfig) -> tuple:
    """What of `config` the worker's machines, database and prune were built from at start; a change needs a restart."""
    return (
        config.database_url,
        config.board_type,
        config.board,
        config.event_log_retention_days,
        config.event_log_archive_dir,
    )
