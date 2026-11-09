"""The `[project.commands]` config table: the project's own command line for each step a shipped skill names.

A name maps to an argv, run with no shell. An element may hold `{task}`, `{worktree}` or `{NAME}` (filled from the
caller), and the whole element `{args}` splices the caller's trailing arguments. No table: no step is mapped, and a skill
does the step as the project's AGENTS.md says.
"""

from __future__ import annotations

import re
import string
from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = ["Project", "ProjectError", "parse_project"]

_KEYS = {"commands"}
_NAME = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")


class ProjectError(ValueError):
    """The table cannot be read; the message names the entry to fix."""


@dataclass(frozen=True)
class Project:
    commands: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Each configured step's argv, by name."""


def _argv(name: str, raw: object) -> tuple[str, ...]:
    who = f"project.commands.{name}"
    if not isinstance(raw, list) or not all(isinstance(element, str) for element in raw):
        raise ProjectError(f"{who}: an argv is a list of strings")
    if not raw:
        raise ProjectError(f"{who}: an argv names at least a program")
    for index, element in enumerate(raw):
        if not element:
            raise ProjectError(f"{who}: element {index} is empty")
        try:
            fields = [field for _, field, _, _ in string.Formatter().parse(element) if field is not None]
        except ValueError as exc:
            raise ProjectError(f"{who}: element {index} has an unbalanced brace") from exc
        if "args" in fields and element != "{args}":
            raise ProjectError(f"{who}: {{args}} must be a whole element")
    return tuple(raw)


def parse_project(raw: object) -> Project:
    """The `[project]` table, or the empty one when the config has none."""
    if raw is None:
        return Project()
    if not isinstance(raw, dict):
        raise ProjectError("project: must be a table")
    if unknown := sorted(raw.keys() - _KEYS):
        raise ProjectError(f"project: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_KEYS))}")
    table = raw.get("commands", {})
    if not isinstance(table, dict):
        raise ProjectError("project.commands: must be a table")
    for name in table:
        if not _NAME.fullmatch(name):
            raise ProjectError(f"project.commands: name {name!r} is not lowercase words joined by hyphens")
    return Project({name: _argv(name, argv) for name, argv in table.items()})
