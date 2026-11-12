"""Whether a session is working or idle at its prompt, read from its transcript.

Claude Code ends each agent turn with a `system` entry (`turn_duration`) and writes an interrupt as a user entry. A
later user or assistant entry means a turn is running. tmux redraws and the session record's `status` say nothing
reliable about it, so only the transcript decides.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ["DEFAULT_SESSIONS", "DEFAULT_TRANSCRIPTS", "holder_activity", "same_holder", "session_activity"]

DEFAULT_TRANSCRIPTS = "~/.claude/projects"
"""Where Claude Code writes each session's transcript, read for a terminal halt: `[board] transcripts`."""
DEFAULT_SESSIONS = "~/.claude/sessions"
"""Where Claude Code registers each running session, `<pid>.json`, read for a live holder: `[board] sessions`."""

TURNS = frozenset({"user", "assistant"})
TURN_END = "turn_duration"
INTERRUPT = "[Request interrupted"
SESSION_ID = re.compile(r"[\w-]+")
BRIDGE_ID = re.compile(r"(?:https?://\S+/)?(?:session|cse)_(\w+)/?")
BRIDGE_FIELD = re.compile(r'"bridgeSessionId"\s*:\s*"([^"]+)"')
NAME_FIELD = re.compile(r'"agentName"\s*:\s*"([^"]+)"')
HEAD_BYTES = 16 * 1024
TAIL_BYTES = 64 * 1024
MISS_TTL_S = 30.0
"""How long a session with no transcript stays unlooked-for: each lookup globs every transcript-project directory."""
_BRIDGES: dict[tuple[Path, str], tuple[float, frozenset[str]]] = {}
_PATHS: dict[tuple[Path, str], Path] = {}
_MISSES: dict[tuple[Path, str], float] = {}
_clock = time.monotonic


def _seconds(stamp: str) -> float:
    return datetime.fromisoformat(stamp).timestamp()


def _text(entry: dict[str, Any]) -> str:
    """The text of a user entry's message, whether Claude Code wrote it as a string or as content parts."""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    parts = content if isinstance(content, list) else []
    return " ".join(part.get("text", "") for part in parts if isinstance(part, dict))


def _decides(entry: dict[str, Any]) -> bool:
    return entry.get("type") in TURNS or (entry.get("type") == "system" and entry.get("subtype") == TURN_END)


def _ended(entry: dict[str, Any]) -> bool:
    if entry.get("type") == "system":
        return True
    return entry.get("type") == "user" and _text(entry).startswith(INTERRUPT)


def _tail(path: Path, size: int) -> list[str]:
    with path.open("rb") as transcript:
        start = max(0, path.stat().st_size - size)
        transcript.seek(start)
        lines = transcript.read().decode(errors="replace").splitlines()
    return lines[1:] if start else lines  # a read from mid-file starts inside a line


def _transcript(root: Path, session: str) -> Path | None:
    if not SESSION_ID.fullmatch(session):
        return None
    key = (root, session)
    known = _PATHS.get(key)
    if known is not None and known.exists():
        return known
    if _clock() < _MISSES.get(key, 0.0):
        return None
    path = next(root.glob(f"*/{session}.jsonl"), None)
    if path is None:
        _MISSES[key] = _clock() + MISS_TTL_S
    else:
        _PATHS[key] = path
    return path


def session_activity(root: Path, session: str, *, now: float, tail: int = TAIL_BYTES) -> dict[str, Any] | None:
    """`{"state": "idle", "last_turn_at", "idle_s"}` after a finished turn, `{"state": "working", "last_turn_at"}`
    mid-turn; None when `session` names no transcript under `root` or none of its last `tail` bytes is a turn."""
    path = _transcript(root, session)
    if path is None:
        return None
    for line in reversed(_tail(path, tail)):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and _decides(entry) and entry.get("timestamp"):
            stamp = entry["timestamp"]
            if _ended(entry):
                return {"state": "idle", "last_turn_at": stamp, "idle_s": int(now - _seconds(stamp))}
            return {"state": "working", "last_turn_at": stamp}
    return None


def _local_id(sessions: Path, assignee: str) -> str:
    """The transcript id of the running session `assignee` names: itself, or the session whose record carries the
    bridge id a claude.ai URL ends in; empty when no running session's record names it."""
    bridge = assignee.rstrip("/").rsplit("/", 1)[-1] if assignee.startswith("http") else ""
    if not bridge:
        return assignee
    for record in sessions.glob("*.json"):
        try:
            data = json.loads(record.read_text())
        except OSError, ValueError:
            continue
        if isinstance(data, dict) and data.get("bridgeSessionId") == bridge:
            return str(data.get("sessionId", ""))
    return ""


def holder_activity(transcripts: Path, sessions: Path, assignee: str, *, now: float) -> dict[str, Any] | None:
    """`session_activity` of the session holding a task, whether its assignee is the local session id or the claude.ai
    URL of its bridge; None when the holder is not a running session with a transcript."""
    return session_activity(transcripts, _local_id(sessions, assignee), now=now)


def _head(path: Path) -> str:
    with path.open("rb") as transcript:
        return transcript.read(HEAD_BYTES).decode(errors="replace")


def _aliases_of(transcripts: Path, session: str) -> frozenset[str]:
    key = (transcripts, session)
    kept = _BRIDGES.get(key)
    if kept is not None and _clock() < kept[0]:
        return kept[1]
    paths = transcripts.glob(f"*/{session}.jsonl") if SESSION_ID.fullmatch(session) else ()
    texts = [_head(path) + "\n".join(_tail(path, TAIL_BYTES)) for path in paths]
    fields = BRIDGE_FIELD.findall("\n".join(texts))
    bridges = (match[1] for match in map(BRIDGE_ID.fullmatch, fields) if match)
    names = (name.lower() for name in NAME_FIELD.findall("\n".join(texts)))
    aliases = frozenset((*bridges, *names))
    _BRIDGES[key] = (_clock() + MISS_TTL_S, aliases)
    return aliases


def holder_keys(assignee: str, transcripts: Path | None = None) -> frozenset[str]:
    """Every identity a session's claim may name: for its local Claude UUID, the UUID, each bridge id
    (`session_x`, `cse_x`) and the lowercased name (`task-11650`) its transcripts give it; for a bridge id or Remote
    Control URL, that bridge id; for a session name, its lowercase."""
    if bridge := BRIDGE_ID.fullmatch(assignee):
        return frozenset({bridge[1]})
    return _aliases_of(transcripts or Path(DEFAULT_TRANSCRIPTS).expanduser(), assignee) | {assignee, assignee.lower()}


def same_holder(held: str | None, wanted: str, transcripts: Path | None = None) -> bool:
    """Whether the assignee `held` and the session `wanted` name one session, in any of its forms."""
    held = held or ""
    if not held:
        return False
    return held == wanted or not holder_keys(held, transcripts).isdisjoint(holder_keys(wanted, transcripts))
