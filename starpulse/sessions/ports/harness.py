"""What StarPulse's runtime, scheduler and views ask of the harness a session runs in: the configured adapter answers, never a read of its files by the core."""

from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import Any, Protocol

from starpulse.sessions.ports.identity import SessionIdentity
from starpulse.sessions.ports.notify import Line, Notifier


class SessionHarness(Protocol):
    name: str
    transcripts: Path
    """The directory the harness writes each session's transcript under."""
    skills_dir: str
    """Where the harness discovers skills, relative to a project or the home directory."""

    def identity(self) -> SessionIdentity:
        """How this harness tells one session from another."""
        ...

    def launch(self, task: str, verb: str, profile: str | None) -> list[str]:
        """The command that starts `task`'s session, `verb` its prompt and `profile` the agent it runs as."""
        ...

    def activity(self, assignee: str, now: float) -> dict[str, Any]:
        """What the session holding a task is doing, `{"state": "unknown"}` when the holder is no running session."""
        ...

    def transcript_written(self, session: str) -> float | None:
        """When the session's transcript was last written; None for no session or no transcript."""
        ...

    def entrypoint(self, session: str) -> str:
        """How the session's running process was started, empty when none runs."""
        ...

    def local_id(self, session: str) -> str:
        """The id of the running session `session` names, under any of its ids; empty when none runs."""
        ...

    def consumer_id(self, name: str) -> str:
        """The local id of the running session a consumer named for a holder URL resolves to; empty for any other name."""
        ...

    def consumer_ids(self, names: Collection[str]) -> set[str]:
        """`consumer_id` of each of `names` that names a holder URL, from one read."""
        ...

    def process(self, session: str) -> tuple[str, int] | None:
        """The local id and pid of the session's running process, None when none runs."""
        ...

    def socket(self, session: str) -> str | None:
        """The inbox socket of the session's running process, None when none runs."""
        ...

    def notifier(self, resume: Sequence[str], delivered: Callable[[str, Sequence[Line]], None]) -> Notifier:
        """The notifier that posts to a live session's inbox, else runs `resume` to wake it; `delivered` hears each delivery."""
        ...

    def end_with(self, command: Sequence[str]) -> Callable[[str, str], None] | None:
        """The call that ends a task's sessions by running `command`; None when `command` is empty."""
        ...
