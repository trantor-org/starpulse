"""Whether a task's assignee and a session are one session, whatever id each names it by: the harness adapter answers."""

from collections.abc import Iterator
from contextlib import contextmanager

from starpulse.sessions.ports.identity import SessionIdentity

_identity: SessionIdentity | None = None


def current() -> SessionIdentity:
    """The configured harness identity; Claude Code's, read from its own session records, until `using` names another."""
    global _identity
    if _identity is None:
        import os
        from pathlib import Path

        from starpulse.event_log.claude_sessions import DEFAULT_TRANSCRIPTS, sessions_dir
        from starpulse.sessions.adapters.outbound.claude_code_identity import ClaudeCodeIdentity

        _identity = ClaudeCodeIdentity(Path(DEFAULT_TRANSCRIPTS).expanduser(), sessions_dir(os.environ))
    return _identity


@contextmanager
def using(identity: SessionIdentity) -> Iterator[None]:
    global _identity
    previous, _identity = _identity, identity
    try:
        yield
    finally:
        _identity = previous


def same_session(held: str | None, wanted: str) -> bool:
    """Whether the assignee `held` and the session `wanted` name one session, in any of its ids."""
    if not held:
        return False
    return held == wanted or not current().aliases(held).isdisjoint(current().aliases(wanted))
