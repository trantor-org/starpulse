"""Scopes the harness's own tools to the lane a session holds: the worktree's local Claude Code settings deny every
native tool the lane does not allow, and the harness applies an edit on the session's next turn."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

__all__ = ["NATIVE", "scope"]

#: The harness tools a lane's `tools` allow or leave out; a tool not listed here is never denied.
NATIVE = ("Agent", "Bash", "Edit", "Glob", "Grep", "NotebookEdit", "Read", "WebFetch", "WebSearch", "Write")


def scope(worktree: Path, allowed: Iterable[str]) -> None:
    """Deny the native tools outside `allowed` in `worktree`'s local settings. A lane that allows none is not scoped,
    so a policy with no tool rows strands no session. A rule the operator wrote stays: only the denials this function
    added, recorded beside the settings, are replaced."""
    directory = worktree / ".claude"
    path, ledger = directory / "settings.local.json", directory / "lane_scope.json"
    settings = json.loads(path.read_text()) if path.exists() else {}
    permissions = settings.setdefault("permissions", {})
    ours = set(json.loads(ledger.read_text()) if ledger.exists() else [])
    kept = [rule for rule in permissions.get("deny", []) if rule not in ours]
    allowed = set(allowed)
    added = [tool for tool in NATIVE if allowed and tool not in allowed and tool not in kept]
    permissions["deny"] = [*kept, *added]
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    ledger.write_text(json.dumps(added))
