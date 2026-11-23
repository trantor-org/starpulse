"""The session that holds a task: its frontmatter `assignee`, which the task actor alone writes."""

from collections.abc import Mapping
from typing import Any

__all__ = ["assignee_of"]


def assignee_of(frontmatter: Mapping[str, Any]) -> str:
    """The session that holds the task: its frontmatter `assignee`, else empty. A list is a profile, not a session."""
    value = frontmatter.get("assignee")
    return value.strip() if isinstance(value, str) else ""
