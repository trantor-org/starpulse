"""The `[sweeper]` table of the StarPulse config: the pass interval and the kinds and housekeeping declared as commands."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

#: The kind the sweeper itself provides; a declared kind may not take its name.
BUILT_IN = ("readers", "claims", "waiting", "criteria")


class SweeperError(ValueError):
    """The `[sweeper]` table cannot be run."""


@dataclass(frozen=True)
class Command:
    """One declared kind or housekeeping step."""

    name: str
    command: list[str]
    timeout_s: float = 300.0


@dataclass(frozen=True)
class Sweeper:
    interval_s: float = 3600.0
    kinds: list[Command] = field(default_factory=list)
    housekeeping: list[Command] = field(default_factory=list)


def _number(where: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise SweeperError(f"{where} must be a number above 0, not {value!r}")
    return float(value)


def _commands(where: str, entries: Any, taken: tuple[str, ...]) -> list[Command]:
    if not isinstance(entries, list):
        raise SweeperError(f"{where} must be an array of tables")
    found: list[Command] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) - {"name", "command", "timeout_s"}:
            raise SweeperError(f"{where}: an entry takes only name, command and timeout_s: {entry!r}")
        name, command = entry.get("name"), entry.get("command")
        if not isinstance(name, str) or not name:
            raise SweeperError(f"{where}: an entry needs a name")
        if not isinstance(command, list) or not command or not all(isinstance(a, str) for a in command):
            raise SweeperError(f"{where} {name}: command must be a non-empty array of strings")
        if name in taken or any(name == c.name for c in found):
            raise SweeperError(f"{where} {name}: the name is already taken")
        timeout = _number(f"{where} {name}: timeout_s", entry["timeout_s"]) if "timeout_s" in entry else 300.0
        found.append(Command(name, command, timeout))
    return found


def parse_sweeper(table: Mapping[str, Any] | None) -> Sweeper:
    """The `[sweeper]` table as a `Sweeper`; none gives the defaults. Raises `SweeperError`."""
    if table is None:
        return Sweeper()
    if not isinstance(table, Mapping) or set(table) - {"interval_s", "kinds", "housekeeping"}:
        raise SweeperError("[sweeper] takes only interval_s, kinds and housekeeping")
    return Sweeper(
        interval_s=_number("[sweeper] interval_s", table["interval_s"]) if "interval_s" in table else 3600.0,
        kinds=_commands("[[sweeper.kinds]]", table.get("kinds", []), BUILT_IN),
        housekeeping=_commands("[[sweeper.housekeeping]]", table.get("housekeeping", []), ()),
    )
