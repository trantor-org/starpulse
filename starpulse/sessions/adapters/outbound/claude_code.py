"""Claude Code as the configured harness: its session records, transcripts, inbox sockets and launch command."""

import re
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import Any

from starpulse.event_log import claude_sessions
from starpulse.harness_telemetry.adapters.outbound.claude import ClaudeHarness
from starpulse.sessions.adapters.outbound import claude_code_notify
from starpulse.sessions.ports.notify import Line

#: A consumer named for a claude.ai URL holder: its bridge id.
_URL_HOLDER = re.compile(r"https_claude_ai_code_((?:session|cse)_\w+)")


class ClaudeCodeSessions:
    name = "claude"

    def __init__(self, environ: Mapping[str, str], transcripts: str | None = None) -> None:
        self._sessions = claude_sessions.sessions_dir(environ)
        self._transcripts = Path(transcripts or claude_sessions.DEFAULT_TRANSCRIPTS).expanduser()
        self._launch = ClaudeHarness().launch
        self._written = claude_sessions.transcript_written(self._transcripts)
        self._entrypoint = claude_sessions.entrypoint_of(self._sessions)
        self._process = claude_sessions.live_process(self._sessions)
        self._socket = claude_sessions.live_socket(self._sessions)

    def launch(self, task: str, verb: str, profile: str | None) -> list[str]:
        return self._launch(task, verb, profile)

    def activity(self, assignee: str, now: float) -> dict[str, Any]:
        return claude_sessions.session_activity_of(
            self._transcripts, Path(claude_sessions.DEFAULT_SESSIONS).expanduser(), assignee, now=now
        )

    def transcript_written(self, session: str) -> float | None:
        return self._written(session)

    def entrypoint(self, session: str) -> str:
        return self._entrypoint(session)

    def local_id(self, session: str) -> str:
        return claude_sessions.local_id(self._sessions, session)

    def consumer_id(self, name: str) -> str:
        bridge = _URL_HOLDER.fullmatch(name)
        return self.local_id(f"https://claude.ai/code/{bridge[1]}") if bridge else ""

    def consumer_ids(self, names: Collection[str]) -> set[str]:
        bridges = [bridge[1] for name in names if (bridge := _URL_HOLDER.fullmatch(name))]
        return claude_sessions.local_ids(self._sessions, bridges)

    def process(self, session: str) -> tuple[str, int] | None:
        return self._process(session)

    def socket(self, session: str) -> str | None:
        return self._socket(session)

    def notifier(
        self, resume: Sequence[str], delivered: Callable[[str, Sequence[Line]], None]
    ) -> claude_code_notify.ClaudeCodeNotifier:
        return claude_code_notify.ClaudeCodeNotifier(
            post=claude_code_notify.post_inbox,
            resume=claude_code_notify.resume_with(resume),
            alive=self._socket,
            now=time.monotonic,
            delivered=delivered,
        )

    def end_with(self, command: Sequence[str]) -> Callable[[str, str], None] | None:
        return claude_code_notify.end_with(command)
