"""The session a claim recorded in a task's notes: the `**Assignee:** <id>` marker."""

from __future__ import annotations

import re
from collections.abc import Callable

__all__ = ["NOTES", "claim_fields", "assignee_of", "without_markers", "released", "released_from", "unreleased"]

NOTES = re.compile(r"<!-- SECTION:NOTES:BEGIN -->(.*?)<!-- SECTION:NOTES:END -->", re.S)
_MARKER = re.compile(r"^\*\*Assignee:\*\* (\S+)[ \t]*$", re.M)
_RELEASED_FROM = re.compile(r"^\*\*Released from:\*\* (\S+)[ \t]*$", re.M)


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
    return _RELEASED_FROM.sub("", _MARKER.sub("", notes)).strip()


def released_from(body: str) -> str:
    """The session the last release of this task's claim ended: the last `**Released from:** <id>` line, else empty."""
    notes = NOTES.search(body)
    found = _RELEASED_FROM.findall(notes.group(1)) if notes else []
    return found[-1] if found else ""


def _rewritten(body: str, notes_of: Callable[[str], str]) -> str:
    """`body` with its notes section replaced by `notes_of` of it."""
    return NOTES.sub(lambda notes: notes.group(0).replace(notes.group(1), f"\n{notes_of(notes.group(1))}\n"), body)


def released(body: str) -> str:
    """`body` with its notes' claim markers dropped, which ends the claim, and `**Released from:** <id>` naming the
    session that held it, because a task's next claimant has no other record of whom it replaced."""
    session = assignee_of(body)
    marker = f"**Released from:** {session}" if session else ""
    return _rewritten(body, lambda notes: "\n".join(filter(None, (without_markers(notes), marker))))


def unreleased(body: str) -> str:
    """`body` without the session a release named: a new claim makes it stale."""
    return _rewritten(body, lambda notes: _RELEASED_FROM.sub("", notes).strip())
