"""What an agent session did: the Activity of each tool call, and the Health of each session and of the sessions that
worked one task.

`activities` is the classification every tool signal StarPulse stores carries
(`starpulse.harness_telemetry.activity`): one tool call lifted to labels with no arguments, so the same work recurs
across sessions. A non-shell tool is its bare name, `TOOL_OTHER` when its name is not one; each statement of a shell
call (a tool in `SHELLS`) is its leading command, such as `bin/<script>`, `make <target>`, `git <subcommand>`,
`gh <group> <verb>` or `ssh <host>`, with `SHELL_READ` and `SHELL_SEARCH` for a file read or a search and `SHELL_OTHER`
for a command that is not a name.

`session_health` and `slice_health` are the folds `GET /api/analytics/sessions` serves
(`starpulse.flow_metrics.session_health` documents every number), returned as the DTOs that route encodes, so a reader that
imports them and one that reads the route get the same rows from the same exports.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from starpulse.contracts.api.dto.health import SessionHealth, SliceHealth, TokenCounts
from starpulse.flow_metrics import session_health as _sessions
from starpulse.harness_telemetry.activity import (
    SHELL_OTHER,
    SHELL_READ,
    SHELL_SEARCH,
    SHELLS,
    TOOL_OTHER,
    activities,
)
from starpulse.harness_telemetry.telemetry import held, signals

if TYPE_CHECKING:
    from starpulse._internal.config.config import Config
    from starpulse.contracts.adapters import TaskKeys

__all__ = [
    "SHELLS",
    "SHELL_OTHER",
    "SHELL_READ",
    "SHELL_SEARCH",
    "TOOL_OTHER",
    "SessionHealth",
    "SliceHealth",
    "TokenCounts",
    "activities",
    "session_health",
    "slice_health",
]


def session_health(
    exports: Iterable[Mapping[str, Any]],
    keys: TaskKeys | None = None,
    config: Config | None = None,
    redact: Callable[[str], str] | None = None,
) -> list[SessionHealth]:
    """One row per (session, task) of the Claude Code and Codex OTLP/HTTP log payloads `exports`, oldest first.

    `keys` is the board's task key scheme, which ties a session's branch and claims to a task; with none, every row's
    `task` is None. `config`'s `[analytics]` table is read as `serve` reads it, less its labeller: this calls no
    endpoint, so no prompt carries an intent label. A Claude Code shell command is kept, passed through `redact`, only
    with one, as the receiver keeps it. A record two payloads both carry counts once."""
    analytics = replace(config.analytics, labeller=None) if config is not None else None
    found = held(s for payload in exports for s in signals(dict(payload), redact, analytics=analytics, keys=keys))
    return [SessionHealth.model_validate(row) for row in _sessions.session_health(found, keys, analytics)]


def slice_health(sessions: Iterable[SessionHealth]) -> list[SliceHealth]:
    """One entry per task of the session rows `sessions`, oldest first; a row with no task is in none."""
    return [SliceHealth.model_validate(row) for row in _sessions.slice_health(s.model_dump() for s in sessions)]
