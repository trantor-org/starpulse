"""Tell a start failure no retry can cure from one that may pass later."""

import re

_PERMANENT = re.compile(r"binary is missing|needs \S+ on PATH", re.I)
_TRANSIENT = re.compile(r"did not answer|is still starting", re.I)
_SESSIONS_FULL = re.compile(r"(\d+) of (\d+) task sessions are live", re.I)


def permanent(text: str) -> bool:
    """Whether `text` names a missing binary: starting again fails the same way until the host is changed."""
    return _PERMANENT.search(text) is not None


def transient(text: str) -> bool:
    """Whether `text` names the board or the session-start service not answering, or the task's first start still under way: the next start may pass."""
    return _TRANSIENT.search(text) is not None


def sessions_full(text: str) -> bool:
    """Whether `text` is the session-start service refusing every start because its live-session limit is full."""
    return _SESSIONS_FULL.search(text) is not None


def session_counts(text: str) -> tuple[int, int] | None:
    """The live count and the limit `text` names when the session-start service refuses for a full limit, else None."""
    found = _SESSIONS_FULL.search(text)
    return None if found is None else (int(found[1]), int(found[2]))
