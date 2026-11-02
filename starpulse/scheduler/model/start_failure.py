"""Tell a start failure no retry can cure from one that may pass later."""

from __future__ import annotations

import re

_PERMANENT = re.compile(r"binary is missing|needs \S+ on PATH", re.I)
_SESSIONS_FULL = re.compile(r"\d+ of \d+ task sessions are live", re.I)


def permanent(text: str) -> bool:
    """Whether `text` names a missing binary: starting again fails the same way until the host is changed."""
    return _PERMANENT.search(text) is not None


def sessions_full(text: str) -> bool:
    """Whether `text` is the session-start service refusing every start because its live-session limit is full."""
    return _SESSIONS_FULL.search(text) is not None
