"""The `[project.commands]` config table: the project's own command line for each step a shipped skill names.

A name maps to an argv, run with no shell. An element may hold `{task}`, `{worktree}` or `{NAME}` (filled from the
caller), and the whole element `{args}` splices the caller's trailing arguments. No table: no step is mapped, and a skill
does the step as the project's AGENTS.md says.
"""

import re
import string
from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = ["Project", "ProjectError", "parse_project"]

_KEYS = {"commands", "pending"}
_NAME = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")


class ProjectError(ValueError):
    """The table cannot be read; the message names the entry to fix."""


@dataclass(frozen=True)
class Project:
    commands: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Each configured step's argv, by name."""
    pending: Mapping[str, int] = field(default_factory=dict)
    """The exit code a step ends on while its work is still running, by name; any other non-zero exit is a failure."""


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
    """The `[project]` table a config has; the caller passes none for a config without one."""
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
    pending = raw.get("pending", {})
    if not isinstance(pending, dict):
        raise ProjectError("project.pending: must be a table")
    for name, code in pending.items():
        if name not in table:
            raise ProjectError(f"project.pending: {name!r} is not a [project.commands] step")
        if not isinstance(code, int) or isinstance(code, bool) or not 1 <= code <= 255:
            raise ProjectError(f"project.pending.{name}: an exit code is an integer from 1 to 255")
    return Project({name: _argv(name, argv) for name, argv in table.items()}, pending)
