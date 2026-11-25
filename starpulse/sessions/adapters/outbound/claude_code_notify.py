"""Claude Code's notify capability: one line per subject, the newest, in the session's inbox socket, else a resume of the session.

A live session takes each line as a message on its inbox socket (the path and token are its registration; a process
the sessions directory shows alive is posted at the socket it holds now). The text is wrapped in the envelope that
attests a sender in `bypassPermissions`, as Claude Code holds a peer message that attests none for approval. A session
whose process has exited is resumed under the same session id with those lines as its next turn, so ten events on
one pull request while it was away read as one line. A session resumed a moment ago and not yet
visible in the sessions directory is not resumed again, which would fork it: its events wait for the next delivery.
"""

import json
import logging
import socket
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from starpulse.sessions.ports.notify import Line, Registration

logger = logging.getLogger(__name__)

#: Seconds after a resume during which the session counts as starting and is not resumed again.
RESUME_GRACE_S = 120.0
_SOCKET_TIMEOUT_S = 30.0
_RESUME_TIMEOUT_S = 120.0


def attested(text: str) -> str:
    return f'<cross-session-message from-mode="bypass">\n{text}\n</cross-session-message>'


def post_inbox(sock: str, token: str, text: str) -> None:
    """Post the attested `text` to a session's inbox socket as a user message after an auth line; `OSError` when it refuses."""
    lines = [
        {"type": "auth", "token": token},
        {"type": "user", "message": {"role": "user", "content": text}},
    ]
    payload = "".join(json.dumps(line) + "\n" for line in lines).encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(_SOCKET_TIMEOUT_S)
        conn.connect(sock)
        conn.sendall(payload)
        conn.shutdown(socket.SHUT_WR)
        while conn.recv(4096):
            pass


def resume_with(command: Sequence[str]) -> Callable[[Registration, str], bool]:
    """Resume by running `command` with the session id and the prompt appended, in the session's directory.

    `{session}` and `{cwd}` in an element of `command` are replaced by the session's id and directory; a session whose
    directory is gone is not resumed.
    """

    def resume(registration: Registration, prompt: str) -> bool:
        if not Path(registration.cwd).is_dir():
            return False
        argv = [part.replace("{session}", registration.session).replace("{cwd}", registration.cwd) for part in command]
        try:
            done = subprocess.run(  # fixed argv, no shell
                [*argv, registration.session, prompt],
                cwd=registration.cwd,
                capture_output=True,
                timeout=_RESUME_TIMEOUT_S,
                check=False,
            )
        except OSError, subprocess.TimeoutExpired:
            return False
        return done.returncode == 0

    return resume


def end_with(command: Sequence[str]) -> Callable[[str, str], None] | None:
    """End a task's sessions by running `command` with `{task}` in an element replaced by the task id and `{lane}` by the
    lane the task entered, empty when the caller names none; none when empty."""
    if not command:
        return None

    def end(task: str, lane: str = "") -> None:
        argv = [part.replace("{task}", task).replace("{lane}", lane) for part in command]
        try:
            done = subprocess.run(
                argv, capture_output=True, timeout=_RESUME_TIMEOUT_S, check=False
            )  # fixed argv, no shell
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("bridge: ending %s failed: %s", task, exc)
            return
        if done.returncode:
            logger.warning("bridge: ending %s exited %d", task, done.returncode)

    return end


class ClaudeCodeNotifier:
    def __init__(
        self,
        *,
        post: Callable[[str, str, str], None],
        resume: Callable[[Registration, str], bool],
        alive: Callable[[str], str | None],
        now: Callable[[], float],
        delivered: Callable[[str, Sequence[Line]], None] = lambda session, lines: None,
    ) -> None:
        self._post, self._resume, self._alive, self._now = post, resume, alive, now
        self._delivered = delivered
        self._resumed: dict[str, float] = {}

    def notify(self, registration: Registration, lines: Sequence[Line]) -> bool:
        """Whether the events reached the session; an event that did not is delivered again. Only the newest event of
        each subject is sent: an older one is superseded."""
        lines = list({line.subject: line for line in lines}.values())
        live = self._alive(registration.session)
        posted: list[Line] = []
        try:
            for line in lines:
                self._post(live or registration.socket, registration.token, attested(line.text))
                posted.append(line)
        except OSError:
            self._delivered(registration.session, posted)
            if live:
                return False
            return self._resume_once(registration, lines)
        self._delivered(registration.session, posted)
        return True

    def _resume_once(self, registration: Registration, lines: Sequence[Line]) -> bool:
        now = self._now()
        last = self._resumed.get(registration.session)
        if last is not None and now - last < RESUME_GRACE_S:
            return False
        if not self._resume(registration, "\n".join(line.text for line in lines)):
            return False
        self._resumed[registration.session] = now
        self._delivered(registration.session, lines)
        return True
