"""The signals session and slice health fold, read from a Cursor agent transcript.

Cursor writes `agent-transcripts/<conversation-id>/<conversation-id>.jsonl` and, beside it, `compaction/segment_*.md`
for each compaction. A line is a user prompt, an agent step (text and `tool_use` blocks) or a `turn_ended`. The
transcript records no model, effort, token count, tool result or per-line time, so:

- a step is a `request` with no model, and a tool call a `tool` signal that is `ok` (its result is not recorded);
- every signal takes the time of the last prompt `<timestamp>` (to the minute) before it, so no duration is defined and
  `agent_s`, `idle_s` and `operator_wait_s` stay 0;
- a prompt is `human` when it carries a `<user_query>` and `injected` otherwise (a timestamp alone is no prompt);
- a `turn_ended` with status `error` is an `interrupt`, and each compaction segment one `compaction`;
- a shell command's claim, `git switch` and kept command are read as the OTLP reader reads them.

Subagent transcripts name no parent step, so they are not read. No signal is `captured`: a row has no model family, so
it is left out of every ranking (decision 8 of Agent Tasks Are Optimized on Steps per Clean Completion).
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.signals import CURSOR, Signal, claim_key, claimed
from starpulse.event_log.opening import open_event_log
from starpulse.harness_telemetry.activity import SHELLS, activities, elide_heredocs, paths
from starpulse.harness_telemetry.intent_classification import intent_label
from starpulse.harness_telemetry.telemetry import _SWITCH, TelemetryLog, redactor, telemetry_log

__all__ = ["CURSOR", "ingest", "main", "transcript_signals"]

_STAMP = re.compile(r"<timestamp>[^,]*, (\w+ \d+, \d{4}, \d+:\d{2} [AP]M) \(UTC([+-]\d+)(?::(\d{2}))?\)</timestamp>")
_QUERY = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.DOTALL)


def _stamp(text: str) -> float | None:
    """The epoch second of the prompt `<timestamp>` in `text`, which names its own UTC offset."""
    if (found := _STAMP.search(text)) is None:
        return None
    sign = -1 if found[2].startswith("-") else 1
    offset = timedelta(hours=int(found[2]), minutes=sign * int(found[3] or 0))
    return datetime.strptime(found[1], "%b %d, %Y, %I:%M %p").replace(tzinfo=timezone(offset)).timestamp()


def _blocks(record: dict[str, Any]) -> list[dict[str, Any]]:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _tool_input(block: dict[str, Any]) -> dict[str, Any]:
    """A tool call's input, its `path` also named `file_path` as the activity vocabulary reads file tools."""
    given = block.get("input")
    given = given if isinstance(given, dict) else {}
    return {**given, "file_path": given["path"]} if "path" in given else given


def _prompt(text: str, reading: Analytics) -> dict[str, Any] | None:
    """A user line's prompt fields, or None when it is only a timestamp."""
    if not _STAMP.sub("", text).strip():
        return None
    if (query := _QUERY.search(text)) is None:
        return {"detail": "injected"}
    label = intent_label(reading.labeller, query[1]) if reading.labeller else ""
    return {"detail": "human", "label": label}


def _step(
    key: str, blocks: list[dict[str, Any]], reading: Analytics, keys: TaskKeys | None, redact: Callable | None
) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """The `(kind, key, fields)` of one agent step: a request, then its tool calls and what each command says."""
    yield "request", key, {}
    for at, block in enumerate(b for b in blocks if b.get("type") == "tool_use"):
        tool, tool_input = str(block.get("name") or ""), _tool_input(block)
        reads, writes = paths(tool, tool_input, "")
        command = tool_input.get("command") if tool in SHELLS else None
        command = command if isinstance(command, str) else ""
        stored = redact(elide_heredocs(command)) if redact and command else ""
        tool_key = f"{key}:{at}"
        yield (
            "tool",
            tool_key,
            {
                "name": tool,
                "activities": tuple(activities(tool, tool_input)),
                "reads": tuple(reads),
                "writes": tuple(writes),
                "command": stored,
            },
        )
        if switch := _SWITCH.search(command):
            yield "branch", f"{tool_key}:branch", {"name": switch[2]}
        if (task := claimed(command, reading.claims, keys)) is not None:
            yield "claim", claim_key(tool_key), {"name": task}


def transcript_signals(
    path: Path,
    *,
    keys: TaskKeys | None = None,
    analytics: Analytics | None = None,
    redact: Callable[[str], str] | None = None,
) -> list[Signal]:
    """The signals the transcript at `path` holds, in line order; its conversation id names the session."""
    reading = analytics or Analytics()
    session, at = path.stem, path.stat().st_mtime
    found: list[Signal] = []

    def add(kind: str, key: str, fields: dict[str, Any]) -> None:
        found.append(Signal(CURSOR, session, kind, at, key, captured=False, **fields))

    for index, line in enumerate(path.read_text().splitlines()):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        key = f"{CURSOR}:{session}:{index}"
        if not isinstance(record, dict):
            continue
        if record.get("type") == "turn_ended" and record.get("status") == "error":
            add("interrupt", key, {})
        elif record.get("role") == "user":
            text = "".join(str(b.get("text") or "") for b in _blocks(record))
            at = _stamp(text) or at
            if (prompt := _prompt(text, reading)) is not None:
                add("prompt", key, prompt)
        elif record.get("role") == "assistant":
            for kind, step_key, fields in _step(key, _blocks(record), reading, keys, redact):
                add(kind, step_key, fields)
    for segment in sorted(path.parent.glob("compaction/segment_*.md")):
        add("compaction", f"{CURSOR}:{session}:{segment.stem}", {})
    return found


def ingest(
    root: Path,
    telemetry: TelemetryLog,
    *,
    keys: TaskKeys | None,
    analytics: Analytics,
    redact: Callable[[str], str] | None = None,
    hours: float = 48.0,
    now: float | None = None,
) -> int:
    """Publish the signals of every transcript under `root` (`<project>/agent-transcripts/<id>/<id>.jsonl`) written in
    the last `hours`; a transcript read again adds nothing, as each signal's key is the line it came from. The number
    of transcripts read."""
    floor = (time.time() if now is None else now) - hours * 3600
    read = 0
    for path in sorted(root.glob("*/agent-transcripts/*/*.jsonl")):
        if path.stat().st_mtime >= floor:
            telemetry.publish(transcript_signals(path, keys=keys, analytics=analytics, redact=redact))
            read += 1
    return read


def main(
    argv: list[str] | None = None,
    *,
    discover: Callable[[Path | None], Path | None],
    load: Callable[[Path | None], Any],
) -> None:  # pragma: no mutate block — process boundary
    """Read the transcripts; `discover` and `load` read the root config, which the runtime owns and passes in."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--root", type=Path, default=Path.home() / ".cursor" / "projects", help="Cursor's projects dir")
    parser.add_argument("--hours", type=float, default=48.0, help="read transcripts written in the last N hours")
    parser.add_argument("--config", type=Path, help="the TOML config whose database holds the event log")
    parser.add_argument("--key", default=r"TASK-\d+", help="a whole task key")
    parser.add_argument(
        "--branch", default=r"(?i)(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", help="group 1 names the key"
    )
    parser.add_argument("--key-format", default="TASK-{}", help="wraps the branch's group 1 into the key")
    parser.add_argument(
        "--redactor", metavar="MODULE:FUNCTION", help="the filter a stored shell command passes through"
    )
    args = parser.parse_args(argv)
    keys = TaskKeys(key=re.compile(args.key), branch=re.compile(args.branch), key_format=args.key_format)
    try:
        path = discover(args.config)
        config = load(path)
        log = open_event_log(config.database_url, path)
        analytics = config.analytics
        redact = redactor(args.redactor) if args.redactor else None
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    telemetry = telemetry_log(config.telemetry_loki_url, log)
    read = ingest(args.root, telemetry, keys=keys, analytics=analytics, redact=redact, hours=args.hours)
    print(f"cursor: read {read} transcript(s) under {args.root}", flush=True)
