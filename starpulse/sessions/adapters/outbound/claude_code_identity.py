"""Claude Code's answer to which ids name one session: its registry of running sessions, then its transcripts."""

import re
import time
from collections.abc import Callable
from pathlib import Path

from starpulse.event_log.claude_sessions import (
    BRIDGE_ID,
    MISS_TTL_S,
    SESSION_ID,
    TAIL_BYTES,
    live_session,
    record_of,
    tail,
)

_BRIDGE_FIELD = re.compile(r'"bridgeSessionId"\s*:\s*"([^"]+)"')
_NAME_FIELD = re.compile(r'"agentName"\s*:\s*"([^"]+)"')
_HEAD_BYTES = 16 * 1024


def _head(path: Path) -> str:
    with path.open("rb") as transcript:
        return transcript.read(_HEAD_BYTES).decode(errors="replace")


def _ends(path: Path) -> str:
    try:
        return _head(path) + "\n".join(tail(path, TAIL_BYTES))
    except FileNotFoundError:
        return ""


class ClaudeCodeIdentity:
    """Every id a Claude Code session answers to, and whether the harness confirms it running.

    A running session's own record declares its ids (`sessionId`, `bridgeSessionId`, `name`), so a hand-started
    session is known with no process or transcript read; the transcripts of a session that has ended or been resumed
    still give the bridge id and name it ran under.
    """

    def __init__(self, transcripts: Path, sessions: Path, clock: Callable[[], float] = time.monotonic) -> None:
        self._transcripts, self._sessions, self._clock = transcripts, sessions, clock
        self._kept: dict[str, tuple[float, frozenset[str]]] = {}

    def aliases(self, session: str) -> frozenset[str]:
        """Every id a claim of `session` may name: for a bridge id or Remote Control URL, that bridge id; else the id,
        its lowercase, and each id its running record or transcripts declare."""
        if bridge := BRIDGE_ID.fullmatch(session):
            return frozenset({bridge[1]})
        return self._from_record(session) | self._from_transcripts(session) | {session, session.lower()}

    def live(self, session: str) -> bool:
        """Whether a running Claude Code process is registered for `session`, by any id it declares."""
        return live_session(self._sessions, session)

    def _from_record(self, session: str) -> frozenset[str]:
        if (record := record_of(self._sessions, session)) is None:
            return frozenset()
        bridge = BRIDGE_ID.fullmatch(str(record.get("bridgeSessionId") or ""))
        name = str(record.get("name") or "").lower()
        return frozenset(filter(None, (str(record.get("sessionId") or ""), bridge and bridge[1], name)))

    def _from_transcripts(self, session: str) -> frozenset[str]:
        kept = self._kept.get(session)
        if kept is not None and self._clock() < kept[0]:
            return kept[1]
        paths = self._transcripts.glob(f"*/{session}.jsonl") if SESSION_ID.fullmatch(session) else ()
        text = "\n".join(map(_ends, paths))
        bridges = (match[1] for match in map(BRIDGE_ID.fullmatch, _BRIDGE_FIELD.findall(text)) if match)
        found = frozenset((*bridges, *(name.lower() for name in _NAME_FIELD.findall(text))))
        self._kept[session] = (self._clock() + MISS_TTL_S, found)
        return found
