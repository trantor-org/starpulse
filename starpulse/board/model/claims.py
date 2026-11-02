"""The session that holds a task: its frontmatter `assignee`.

A release removes `assignee` and writes `released_from`, the session it ended. No notes marker records a claim."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

__all__ = ["assignee_of", "claimed", "released", "released_from"]


def _field(frontmatter: Mapping[str, Any], key: str) -> str:
    """The session id text `key` holds in `frontmatter`, else empty: a list is a profile, not a session."""
    value = frontmatter.get(key)
    return value.strip() if isinstance(value, str) else ""


def assignee_of(frontmatter: Mapping[str, Any]) -> str:
    """The session that holds the task: its frontmatter `assignee`, else empty."""
    return _field(frontmatter, "assignee")


def released_from(frontmatter: Mapping[str, Any]) -> str:
    """The session the last release of this task's claim ended: its frontmatter `released_from`, else empty."""
    return _field(frontmatter, "released_from")


def released(frontmatter: MutableMapping[str, Any]) -> None:
    """End the claim: `frontmatter` loses `assignee` and gains `released_from` naming the session that held it, because a
    task's next claimant has no other record of whom it replaced."""
    session = assignee_of(frontmatter)
    frontmatter.pop("assignee", None)
    frontmatter.pop("released_from", None)
    if session:
        frontmatter["released_from"] = session


def claimed(frontmatter: MutableMapping[str, Any], session: str) -> None:
    """Record `session`'s claim in `frontmatter`: it is the `assignee`, and a release's `released_from` is stale."""
    frontmatter["assignee"] = session
    frontmatter.pop("released_from", None)
