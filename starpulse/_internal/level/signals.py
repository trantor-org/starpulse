"""The record session and slice health fold: one thing a harness session did, read from its telemetry export.

`starpulse._internal.harnesses.telemetry` reads the exports into these; `starpulse._internal.level.sessions` folds them.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CLAUDE_CODE", "CODEX", "Signal"]

CLAUDE_CODE = "claude-code"
CODEX = "codex"


@dataclass(frozen=True)
class Signal:
    """One thing a session did, as the export recorded it.

    `kind` is `start`, `prompt` (a human's, `name` its slash command), `request` (one model call), `tool` (a tool
    result, `ok` its success), `decision` (a tool permission, `ok` accepted, `detail` its source), `skill`,
    `compaction` (`name` its trigger), `interrupt` or `branch` (`name` the ref a shell switched to). `origin` is
    `main`, `side` (a subagent) or `auxiliary` (a compaction's own call). `key` is unique to the record, so a
    replayed export gives the same signals. A `tool` signal carries the `activities` the call performed, in order, as
    a closed vocabulary with no arguments, and the `reads` and `writes` it named, as the export gave them.
    """

    harness: str
    session: str
    kind: str
    time: float
    key: str
    branch: str | None = None
    name: str = ""
    model: str = ""
    effort: str = ""
    ok: bool = True
    origin: str = "main"
    detail: str = ""
    seconds: float = 0.0
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int = 0
    cost: float | None = None
    activities: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
