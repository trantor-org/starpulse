"""Tell a start failure no retry can cure from one that may pass later."""

from __future__ import annotations

import re

_PERMANENT = re.compile(r"binary is missing|needs \S+ on PATH", re.I)


def permanent(text: str) -> bool:
    """Whether `text` names a missing binary: starting again fails the same way until the host is changed."""
    return _PERMANENT.search(text) is not None
