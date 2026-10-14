"""The record session and slice health fold: one thing a harness session did, read from its telemetry export.

`starpulse._internal.harnesses.telemetry` reads the exports into these; `starpulse._internal.level.sessions` folds them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from starpulse.contracts.task_keys import TaskKeys

__all__ = ["CLAUDE_CODE", "CODEX", "CURSOR", "Signal", "claim_key", "claimed", "main_thread_source"]

CLAUDE_CODE = "claude-code"
CODEX = "codex"
CURSOR = "cursor"
_MAIN_THREAD = "repl_main_thread"


def main_thread_source(query_source: str) -> str:
    """`repl_main_thread` for that source or one Claude Code suffixes with `:` (`repl_main_thread:outputStyle:custom`
    under a custom output style); any other source unchanged."""
    return _MAIN_THREAD if query_source.startswith(_MAIN_THREAD + ":") else query_source


@dataclass(frozen=True)
class Signal:
    """One thing a session did, as the export recorded it.

    `kind` is `start`, `prompt` (a human's, `name` its slash command), `request` (one model call), `tool` (a tool
    result, `ok` its success), `decision` (a tool permission, `ok` accepted, `detail` its source), `skill`,
    `hook` (a hook run inside a turn, `name` its event and matcher, `seconds` its total duration), `compaction` (`name` its trigger), `reply` (a text answer), `interrupt`, `branch` (`name` the ref a shell
    switched to), `claim` (`name` the task a command or a `Skill` call named) or `deliver` (a shell command that
    matched the instance's completion call). `origin` is
    `main`, `side` (a subagent) or `auxiliary` (a compaction's own call). `key` is unique to the record, so a
    replayed export gives the same signals. A `tool` signal carries the `activities` the call performed, in order, as
    a closed vocabulary with no arguments, and the `reads` and `writes` it named, as the export gave them. `shell_write` is
    True for a shell command that writes a file, which names no path (`starpulse._internal.harnesses.activity.writes_file`,
    set when the stored signal is read). `agent` is
    the subagent that made a `request` or `tool` step, empty for the main thread. `captured` is False for a harness the
    steps-per-completion ledger does not cover yet (Codex, Cursor): its rows are kept and left out of every ranking.

    `turn` is the export's `prompt.id`, the one user prompt every event it caused shares; empty where the harness
    names none. A `prompt` signal's `detail` is its origin, `human` or `injected` (empty when the export carried no
    prompt text to read it from), and its `label` the intent the instance's labeller gave a `human` one (empty when
    none is configured or it did not answer); the text itself is never a field.
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
    agent: str = ""
    command: str = ""
    captured: bool = True
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
    shell_write: bool = False
    writes: tuple[str, ...] = ()
    turn: str = ""
    label: str = ""


def claim_key(tool_key: str) -> str:
    """The `key` of the `claim` a tool result's signal `tool_key` yields, so a claim minted at ingest and one derived
    from the stored command at read time are one record."""
    return f"{tool_key}:claim"


def claimed(text: str, claims: Iterable[re.Pattern[str]], keys: TaskKeys | None) -> str | None:
    """The task the first matching claim pattern of `claims` names in `text`, when the board's key scheme calls it a
    task. A capture that differs from the board's key only by case (`task-12`) names the key in upper case."""
    for pattern in claims if keys else ():
        if match := pattern.search(text):
            for spelling in (match[1], match[1].upper()):
                if keys.matches(spelling):
                    return spelling
    return None
