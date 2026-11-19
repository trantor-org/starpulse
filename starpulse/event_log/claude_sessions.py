"""The one reader of Claude Code's session records and transcripts for StarPulse.

Claude Code keeps one record per running process, `<sessions>/<pid>.json`, and one transcript per session,
`<transcripts>/<project>/<session>.jsonl`. A record is of a running session only while its pid runs with the start
time the record holds (`procStart`), so a reused pid is no live session: every liveness answer here, a session's
process and its inbox socket, is that one check. A turn is a `user` or `assistant` entry of a transcript; Claude Code
ends each agent turn with a `system` entry (`turn_duration`) and writes an interrupt as a user entry. A later turn
means one is running. tmux redraws and the record's `status` say nothing reliable about it, so only the transcript
decides.
"""

import json
import os
import re
import time
from collections.abc import Callable, Collection, Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

__all__ = [
    "DEFAULT_SESSIONS",
    "DEFAULT_TRANSCRIPTS",
    "holder_activity",
    "last_turn",
    "live_process",
    "live_session",
    "live_socket",
    "local_id",
    "same_holder",
    "session_activity",
    "sessions_dir",
    "terminal_halt",
    "transcript_written",
]

DEFAULT_TRANSCRIPTS = "~/.claude/projects"
"""Where Claude Code writes each session's transcript, read for a terminal halt: `[board] transcripts`."""
DEFAULT_SESSIONS = "~/.claude/sessions"
"""Where Claude Code registers each running session, `<pid>.json`, read for a live holder: `[board] sessions`."""

TURNS = frozenset({"user", "assistant"})
"""The `type` of a transcript entry that is a turn."""
TURN_END = "turn_duration"
"""The `subtype` of the `system` entry that closes a turn."""
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


def transcript_path(root: Path, session: str) -> Path | None:
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


def last_turn(root: Path, session: str, *, size: int = TAIL_BYTES, ends: bool = False) -> dict[str, Any] | None:
    """The newest timestamped turn of `session`'s transcript under `root`, or with `ends` the `system` entry that closes
    one; None when it has no transcript or none of its last `size` bytes is one (a transcript reaches 100 MB)."""
    path = transcript_path(root, session)
    if path is None:
        return None
    for line in reversed(_tail(path, size)):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or not entry.get("timestamp"):
            continue
        if entry.get("type") in TURNS or (ends and entry.get("type") == "system" and entry.get("subtype") == TURN_END):
            return entry
    return None


TERMINAL_HALTS = ("Autocompact is thrashing",)
"""How the halts that end a session for good open: Claude Code writes each as a synthetic error reply."""


def terminal_halt(last_turn: Callable[[str], dict | None]) -> Callable[[str], tuple[float, str] | None]:
    """The moment and text of the terminal halt a session's transcript ends its turns with, from `last_turn`, the
    session's newest transcript turn; None when its last turn is any other or it has none."""

    def halt(session: str) -> tuple[float, str] | None:
        turn = last_turn(session)
        return _halt(turn) if turn is not None else None

    return halt


def _halt(turn: dict) -> tuple[float, str] | None:
    message = turn.get("message") or {}
    texts = [part.get("text", "") for part in message.get("content") or [] if isinstance(part, dict)]
    text = "".join(texts)
    synthetic = turn.get("isApiErrorMessage") and message.get("model") == "<synthetic>"
    if not synthetic or not text.startswith(TERMINAL_HALTS):
        return None
    return datetime.fromisoformat(turn["timestamp"]).timestamp(), text


def transcript_written(root: Path) -> Callable[[str], float | None]:
    """A reader of when `<root>/<project>/<session>.jsonl` was last written; None for no session or no transcript."""

    def written(session: str) -> float | None:
        path = transcript_path(root, session)
        try:
            return path.stat().st_mtime if path is not None else None
        except FileNotFoundError:
            return None

    return written


def session_activity(root: Path, session: str, *, now: float, tail: int = TAIL_BYTES) -> dict[str, Any] | None:
    """`{"state": "idle", "last_turn_at", "idle_s"}` after a finished turn, `{"state": "working", "last_turn_at"}`
    mid-turn; None when `session` names no transcript under `root` or none of its last `tail` bytes is a turn."""
    entry = last_turn(root, session, size=tail, ends=True)
    if entry is None:
        return None
    stamp = entry["timestamp"]
    if _ended(entry):
        return {"state": "idle", "last_turn_at": stamp, "idle_s": int(now - _seconds(stamp))}
    return {"state": "working", "last_turn_at": stamp}


def sessions_dir(environ: Mapping[str, str]) -> Path:
    """Where Claude Code keeps one record per running process: `$CLAUDE_CONFIG_DIR/sessions`, else `~/.claude/sessions`."""
    return Path(environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "sessions"


def _running(record: dict[str, Any]) -> bool:
    """Whether the recorded pid runs with the recorded start time, so a reused pid is not the session."""
    try:
        started = psutil.Process(int(record["pid"])).create_time() - psutil.boot_time()
        return round(started * os.sysconf("SC_CLK_TCK")) == int(record["procStart"])  # `procStart` is in clock ticks
    except psutil.Error, KeyError, ValueError, TypeError:
        return False


def _running_records(sessions: Path, match: Callable[[dict[str, Any]], bool]) -> Iterator[dict[str, Any]]:
    """The records `match` accepts whose process runs: liveness costs a process lookup, so it is read only for a match."""
    for entry in sorted(sessions.glob("*.json")):
        try:
            data = json.loads(entry.read_text())
        except OSError, ValueError:
            continue
        if isinstance(data, dict) and match(data) and _running(data):
            yield data


def _record_of(sessions: Path, session: str) -> dict[str, Any] | None:
    def names(record: dict[str, Any]) -> bool:
        bridge = record.get("bridgeSessionId")
        return session in (record.get("sessionId"), bridge) or bool(bridge and session.rstrip("/").endswith(f"/{bridge}"))

    return next(_running_records(sessions, names), None) if session else None


def live_session(sessions: Path, session: str) -> bool:
    """Whether the process registered under `sessions` for `session` (its session id, bridge id or Remote Control URL) is still running."""
    return _record_of(sessions, session) is not None


def live_process(sessions: Path) -> Callable[[str], tuple[str, int] | None]:
    """The local session id and pid of the running process of a session (any id `live_session` takes), None when none runs."""

    def find(session: str) -> tuple[str, int] | None:
        record = _record_of(sessions, session)
        return (str(record["sessionId"]), int(record["pid"])) if record and record.get("sessionId") else None

    return find


def live_socket(sessions: Path) -> Callable[[str], str | None]:
    """The inbox socket of the running process of a session, from Claude Code's per-process records in `sessions`."""

    def find(session: str) -> str | None:
        records = _running_records(sessions, lambda record: record.get("sessionId") == session and bool(record.get("messagingSocketPath")))
        record = next(records, None)
        return str(record["messagingSocketPath"]) if record else None

    return find


def local_id(sessions: Path, assignee: str) -> str:
    """The transcript id of the running session `assignee` names: itself, or the session whose record carries the
    bridge id a claude.ai URL ends in; empty when no running session's record names it."""
    bridge = assignee.rstrip("/").rsplit("/", 1)[-1] if assignee.startswith("http") else ""
    if not bridge:
        return assignee
    record = next(_running_records(sessions, lambda record: record.get("bridgeSessionId") == bridge), None)
    return str(record.get("sessionId", "")) if record else ""


def local_ids(sessions: Path, bridges: Collection[str]) -> set[str]:
    """The transcript ids of the running sessions whose records carry one of the `bridges` ids, from one read of the records."""
    wanted = set(bridges)
    if not wanted:
        return set()
    records = _running_records(sessions, lambda record: record.get("bridgeSessionId") in wanted)
    return {str(record.get("sessionId", "")) for record in records}


def holder_activity(transcripts: Path, sessions: Path, assignee: str, *, now: float) -> dict[str, Any] | None:
    """`session_activity` of the session holding a task, whether its assignee is the local session id or the claude.ai
    URL of its bridge; None when the holder is not a running session with a transcript."""
    return session_activity(transcripts, local_id(sessions, assignee), now=now)


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
