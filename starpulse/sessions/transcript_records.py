"""A session's Claude Code transcript records, split by the task each belongs to.

The signals StarPulse stores keep no tool arguments and no message text, so a consumer that needs a tool call's input
and result reads the transcript: `<transcripts>/<project>/<session>.jsonl` (`[board] transcripts`). Nothing is stored;
the files are read when asked (Transcript Records Are Read From the Files, Not Stored ADR).

Attribution is `session_health.attributed`'s: a record's `gitBranch` that names a task, and a shell command or a
`Skill` call's arguments that an `[analytics] claims` pattern matches, claim that task for the records after them, and
the records before the first claim join the first task. A session that names no task is one group under `None`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.signals import CLAUDE_CODE, Signal, claimed
from starpulse.flow_metrics.model.session_health import attributed
from starpulse.harness_telemetry.model.activity import SHELLS, elide_heredocs

__all__ = ["records_by_task", "session_records"]

_RECORD = "record"


def session_records(root: Path, session: str) -> list[dict[str, Any]] | None:
    """One session's records across every copy of its transcript under `root`, or None when it has none.

    Resuming a session from another checkout writes a second `<session>.jsonl` that re-stamps the original's recent
    records under the same `uuid`, so the copies are read earliest-started first and a later copy adds only the uuids
    not yet seen."""
    if not session or Path(session).name != session:
        return None
    copies = [_read(path) for path in sorted(root.glob(f"*/{session}.jsonl"))]
    if not copies:
        return None
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for records in sorted(copies, key=_started):
        for record in records:
            uuid = record.get("uuid")
            if isinstance(uuid, str):
                if uuid in seen:
                    continue
                seen.add(uuid)
            merged.append(record)
    return merged


def records_by_task(
    records: list[dict[str, Any]], keys: TaskKeys, analytics: Analytics
) -> dict[str | None, list[dict[str, Any]]]:
    """`records` grouped by the task each belongs to, in the order the tasks are first named."""
    signals: list[Signal] = []
    branch: str | None = None
    for index, record in enumerate(records):
        given = record.get("gitBranch")
        if isinstance(given, str) and given != branch:
            branch = given
            signals.append(Signal(CLAUDE_CODE, "", "branch", index, f"{index}:branch", branch, name=given))
        signals.extend(
            Signal(CLAUDE_CODE, "", "claim", index, f"{index}:claim", branch, name=task)
            for task in _claims(record, keys, analytics)
        )
        signals.append(Signal(CLAUDE_CODE, "", _RECORD, index, f"{index}:{_RECORD}", branch, name=str(index)))
    groups: dict[str | None, list[dict[str, Any]]] = {}
    for task, signal in attributed(signals, keys) if signals else ():
        if signal.kind == _RECORD:
            groups.setdefault(task, []).append(records[int(signal.name)])
    return groups


def _read(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _started(records: list[dict[str, Any]]) -> str:
    return min((r["timestamp"] for r in records if isinstance(r.get("timestamp"), str)), default="")


def _claims(record: dict[str, Any], keys: TaskKeys, analytics: Analytics) -> list[str]:
    """The tasks the shell commands and `Skill` calls of `record` claim."""
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    found = []
    for block in content if isinstance(content, list) else ():
        if not isinstance(block, dict) or block.get("type") != "tool_use" or not isinstance(block.get("input"), dict):
            continue
        name, given = block.get("name"), block["input"]
        text = given.get("command") if name in SHELLS else given.get("args") if name == "Skill" else None
        if isinstance(text, str) and (task := claimed(elide_heredocs(text), analytics.claims, keys)) is not None:
            found.append(task)
    return found
