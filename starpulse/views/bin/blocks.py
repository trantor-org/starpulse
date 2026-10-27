"""The config blocks the views worker is built from or re-reads, in a leaf module so `runtime.closure` names them without
importing the worker."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from starpulse.board.model.search_config import Search
    from starpulse.contracts.analytics import Analytics
    from starpulse.harness_telemetry.harnesses import Harnesses
    from starpulse.pulls.pins import Repo
    from starpulse.runs.config import Producer


class ApiConfig(Protocol):
    """The config section the page reads; `runtime` loads the root config and hands it in, as no context imports it."""

    database_url: str | None
    board_type: str
    board: Mapping[str, object]
    board_worker: bool
    read_model: bool
    analytics: Analytics
    harnesses: Harnesses | None
    producers: tuple[Producer, ...]
    repos: tuple[Repo, ...]
    search: Search
    session_start_url: str | None
    telemetry_loki_url: str | None
    slow_read_seconds: float
    task_actor: bool
    take_over_command: tuple[str, ...] | None
    tls: tuple[Path, Path] | None


def api_built_blocks(config: ApiConfig) -> tuple:
    """What of `config` the page is built from at start; a change needs a new process."""
    return (config,)
