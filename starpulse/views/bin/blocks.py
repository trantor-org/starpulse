"""The config section the views worker reads, in a leaf module so `runtime` names it without importing the worker."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from starpulse.board.model.search_config import Search
    from starpulse.contracts.analytics import Analytics
    from starpulse.harness_telemetry.model.harnesses import Harnesses
    from starpulse.pulls.model.pins import Repo
    from starpulse.runs.model.config import Producer
    from starpulse.sessions.ports.harness import SessionHarness


class ApiConfig(Protocol):
    """The config section the page reads; `runtime` loads the root config and hands it in, as no context imports it."""

    database_url: str | None
    event_log_archive_dir: str
    board_type: str
    board: Mapping[str, object]
    read_model: bool
    analytics: Analytics
    harnesses: Harnesses | None
    producers: tuple[Producer, ...]
    repos: tuple[Repo, ...]
    search: Search
    session_start_url: str | None
    task_actor: bool
    take_over_command: tuple[str, ...] | None
    webhook_producer: str | None
    webhook_token_env: str | None
    tls: tuple[Path, Path] | None

    def session_harness(self) -> SessionHarness: ...
