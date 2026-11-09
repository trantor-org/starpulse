"""Whether a session is working or idle at its prompt, read from its transcript.

Claude Code ends each agent turn with a `system` entry (`turn_duration`) and writes an interrupt as a user entry. A
later user or assistant entry means a turn is running. tmux redraws and the session record's `status` say nothing
reliable about it, so only the transcript decides.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ["DEFAULT_SESSIONS", "DEFAULT_TRANSCRIPTS", "holder_activity", "holder_key", "same_holder", "session_activity"]

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
HEAD_BYTES = 16 * 1024
_BRIDGES: dict[tuple[Path, str], str] = {}


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


def session_activity(root: Path, session: str, *, now: float, tail: int = 64 * 1024) -> dict[str, Any] | None:
    """`{"state": "idle", "last_turn_at", "idle_s"}` after a finished turn, `{"state": "working", "last_turn_at"}`
    mid-turn; None when `session` names no transcript under `root` or none of its last `tail` bytes is a turn."""
    path = next(root.glob(f"*/{session}.jsonl"), None) if SESSION_ID.fullmatch(session) else None
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


def _bridge_of(transcripts: Path, session: str) -> str:
    """The bridge key a local session's transcript names in its first lines (a `bridge-session` entry); empty when it
    has no transcript or no bridge. A found key is kept, a miss is not: the transcript may not be written yet."""
    if (found := _BRIDGES.get((transcripts, session))) is not None:
        return found
    path = next(transcripts.glob(f"*/{session}.jsonl"), None) if SESSION_ID.fullmatch(session) else None
    if path is None:
        return ""
    with path.open("rb") as transcript:
        field = BRIDGE_FIELD.search(transcript.read(HEAD_BYTES).decode(errors="replace"))
    bridge = BRIDGE_ID.fullmatch(field[1]) if field else None
    if bridge:
        _BRIDGES[transcripts, session] = bridge[1]
    return bridge[1] if bridge else ""


def holder_key(assignee: str, transcripts: Path | None = None) -> str:
    """One identity for a session however a claim names it: its local Claude UUID, its bridge id (`session_x`,
    `cse_x`) or its Remote Control URL. A UUID whose transcript names no bridge is its own key."""
    if bridge := BRIDGE_ID.fullmatch(assignee):
        return bridge[1]
    return _bridge_of(transcripts or Path(DEFAULT_TRANSCRIPTS).expanduser(), assignee) or assignee


def same_holder(held: str | None, wanted: str, transcripts: Path | None = None) -> bool:
    """Whether the assignee `held` and the session `wanted` name one session, in any of its forms."""
    held = held or ""
    return held == wanted or (bool(held) and holder_key(held, transcripts) == holder_key(wanted, transcripts))
