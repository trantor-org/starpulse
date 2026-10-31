"""The session that holds a task: its frontmatter `assignee`, else the `**Assignee:** <id>` marker in its notes.

A release removes `assignee` and writes `released_from`, the session it ended. The markers are written beside the
fields until nothing reads them."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, MutableMapping
from typing import Any

__all__ = [
    "NOTES",
    "assignee_of",
    "claimed",
    "released",
    "released_from",
    "unreleased",
    "without_markers",
]

NOTES = re.compile(r"<!-- SECTION:NOTES:BEGIN -->(.*?)<!-- SECTION:NOTES:END -->", re.S)
_MARKER = re.compile(r"^\*\*Assignee:\*\* (\S+)[ \t]*$", re.M)
_RELEASED_FROM = re.compile(r"^\*\*Released from:\*\* (\S+)[ \t]*$", re.M)


def _field(frontmatter: Mapping[str, Any], key: str) -> str:
    """The session id text `key` holds in `frontmatter`, else empty: a list is a profile, not a session."""
    value = frontmatter.get(key)
    return value.strip() if isinstance(value, str) else ""


def assignee_of(frontmatter: Mapping[str, Any], body: str) -> str:
    """The session that holds the task: its frontmatter `assignee`, else the last `**Assignee:** <id>` line in its notes,
    else empty."""
    notes = NOTES.search(body)
    found = _MARKER.findall(notes.group(1)) if notes else []
    return _field(frontmatter, "assignee") or (found[-1] if found else "")


def without_markers(notes: str) -> str:
    """`notes` without its claim markers, trimmed."""
    return _RELEASED_FROM.sub("", _MARKER.sub("", notes)).strip()


def released_from(frontmatter: Mapping[str, Any], body: str) -> str:
    """The session the last release of this task's claim ended: its frontmatter `released_from`, else the last
    `**Released from:** <id>` line in its notes, else empty."""
    notes = NOTES.search(body)
    found = _RELEASED_FROM.findall(notes.group(1)) if notes else []
    return _field(frontmatter, "released_from") or (found[-1] if found else "")


def _rewritten(body: str, notes_of: Callable[[str], str]) -> str:
    """`body` with its notes section replaced by `notes_of` of it."""
    return NOTES.sub(lambda notes: notes.group(0).replace(notes.group(1), f"\n{notes_of(notes.group(1))}\n"), body)


def released(frontmatter: MutableMapping[str, Any], body: str) -> str:
    """End the claim: `frontmatter` loses `assignee` and gains `released_from` naming the session that held it, because a
    task's next claimant has no other record of whom it replaced. The returned `body` has its notes' markers likewise."""
    session = assignee_of(frontmatter, body)
    frontmatter.pop("assignee", None)
    frontmatter.pop("released_from", None)
    if session:
        frontmatter["released_from"] = session
    marker = f"**Released from:** {session}" if session else ""
    return _rewritten(body, lambda notes: "\n".join(filter(None, (without_markers(notes), marker))))


def claimed(frontmatter: MutableMapping[str, Any], session: str) -> None:
    """Record `session`'s claim in `frontmatter`: it is the `assignee`, and a release's `released_from` is stale."""
    frontmatter["assignee"] = session
    frontmatter.pop("released_from", None)


def unreleased(body: str) -> str:
    """`body` without the session a release named: a new claim makes it stale."""
    return _rewritten(body, lambda notes: _RELEASED_FROM.sub("", notes).strip())
