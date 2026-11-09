"""The `[claude_code]` config table: the Claude Code adapter `starpulse serve` runs, and where it listens.

With the table, the `contexts` child receives Claude Code's OpenTelemetry log export on `host:port` and appends the events
it maps to the event log; without it no adapter runs. Every key is optional.

- `host`: the address to bind (default `127.0.0.1`; a container that exports to the host needs a wider one).
- `port`: the port to bind (default 4318, the OTLP/HTTP port).
- `key`, `branch`, `key_format`: how a session's branch names its task (default `TASK-<n>` from a `task-<n>` branch).
- `redactor`: `MODULE:FUNCTION`, the filter a shell command's text passes through before it is stored; without one no
  command text is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["ClaudeCode", "ClaudeCodeError", "parse_claude_code"]

_KEYS = {"host", "port", "key", "branch", "key_format", "redactor"}


class ClaudeCodeError(ValueError):
    """The table cannot be read; the message names the key to fix."""


@dataclass(frozen=True)
class ClaudeCode:
    host: str = "127.0.0.1"
    port: int = 4318
    key: str = r"TASK-\d+"
    """A whole task key."""
    branch: str = r"(?i)(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)"
    """Group 1 names the key."""
    key_format: str = "TASK-{}"
    """Wraps the branch's group 1 into the key."""
    redactor: str | None = None


def _text(raw: dict[str, object], key: str, default: str | None) -> str | None:
    value = raw.get(key, default)
    if value is not default and (not isinstance(value, str) or not value):
        raise ClaudeCodeError(f"claude_code: {key} must be a non-empty string")
    return value  # type: ignore[return-value]


def parse_claude_code(raw: object) -> ClaudeCode | None:
    """The `[claude_code]` table, or `None` for no table; each refusal names the key to fix."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ClaudeCodeError("claude_code must be a [claude_code] table")
    if unknown := sorted(raw.keys() - _KEYS):
        raise ClaudeCodeError(f"claude_code: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_KEYS))}")
    defaults = ClaudeCode()
    port = raw.get("port", defaults.port)
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        raise ClaudeCodeError("claude_code: port must be a whole number from 1 to 65535")
    table = ClaudeCode(
        host=str(_text(raw, "host", defaults.host)),
        port=port,
        key=str(_text(raw, "key", defaults.key)),
        branch=str(_text(raw, "branch", defaults.branch)),
        key_format=str(_text(raw, "key_format", defaults.key_format)),
        redactor=_text(raw, "redactor", None),
    )
    for name in ("key", "branch"):
        try:
            re.compile(getattr(table, name))
        except re.error as exc:
            raise ClaudeCodeError(f"claude_code: {name} is not a regular expression ({exc})") from exc
    return table
