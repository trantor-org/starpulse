"""The session a claim recorded in a task's notes: the `**Assignee:** <id>` marker."""

from __future__ import annotations

import re

__all__ = ["NOTES", "claim_fields", "assignee_of", "without_markers"]

NOTES = re.compile(r"<!-- SECTION:NOTES:BEGIN -->(.*?)<!-- SECTION:NOTES:END -->", re.S)
_MARKER = re.compile(r"^\*\*Assignee:\*\* (\S+)[ \t]*$", re.M)


def assignee_of(body: str) -> str:
    """The session a claim recorded in the task's notes: the last `**Assignee:** <id>` line there, else empty.

    The marker lives in the notes because the Backlog CLI rewrites a task file's frontmatter and drops a key it
    does not know, while the notes section survives every edit.
    """
    notes = NOTES.search(body)
    found = _MARKER.findall(notes.group(1)) if notes else []
    return found[-1] if found else ""


def claim_fields(body: str) -> dict[str, str]:
    """The `BoardTask` field a claim marker in `body` fills."""
    return {"assignee": assignee_of(body)}


def without_markers(notes: str) -> str:
    """`notes` without its claim markers, trimmed."""
    return _MARKER.sub("", notes).strip()
