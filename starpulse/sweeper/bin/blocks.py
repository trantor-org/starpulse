"""The config blocks the sweeper is built from, in a leaf module so `runtime.closure` names them without importing the
worker."""

from __future__ import annotations

from typing import Protocol

from starpulse.sweeper.config import Sweeper


class SweeperBlocks(Protocol):
    """The config the sweeper is built from; `runtime` loads the root config and hands it in, as no context imports it."""

    database_url: str | None
    event_log_retention_days: int
    event_log_archive_dir: str
    sweeper: Sweeper


def sweeper_built_blocks(config: SweeperBlocks) -> tuple:
    """What of `config` the sweeper's kinds, housekeeping and database were built from at start; a change needs a restart."""
    return (config.database_url, config.event_log_retention_days, config.event_log_archive_dir, config.sweeper)
