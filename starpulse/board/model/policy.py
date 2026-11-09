"""The board's policy as rows: its lanes, the routes between them, who takes each exit, the facts each lane watches, the
rules a write must meet, the vocabularies and the profile cells.

Today the policy is two hand-edited files, the board machine (`states`, `events`, `writers`) and `starpulse.toml`'s
`[board]` (`guards`, `types`, `default_profiles`). `from_files` reads them into a `Policy`; the policy tables hold the
same shape, and a store that holds none is governed by the files until a migration fills them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["Exit", "Lane", "LaneTool", "Policy", "PolicyRule", "Profile", "Route", "Vocabulary", "Watch", "from_files"]


@dataclass(frozen=True)
class Lane:
    name: str
    role: str | None
    position: int
    #: The skill bound to a task on entering the lane; no file declares one today.
    skill: str | None = None


@dataclass(frozen=True)
class Route:
    """A transition: `event` takes a task from lane `source` to `target` when `condition` (its `if`/`unless`) allows."""

    event: str
    source: str
    target: str
    condition: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Exit:
    """`actor` may fire `event`, by `trigger`."""

    event: str
    actor: str
    trigger: str


@dataclass(frozen=True)
class Watch:
    """The task actor fires `event` from `lane` when `fact` holds; `position` orders a lane's facts, first holding wins."""

    lane: str
    fact: str
    event: str
    position: int


@dataclass(frozen=True)
class PolicyRule:
    """A guard: the write described by `on` must meet `require`, else it is refused with `reason`."""

    position: int
    on: Mapping[str, Any]
    require: Mapping[str, Any]
    reason: str
    skill: str
    unless_actor: list[str]


@dataclass(frozen=True)
class Vocabulary:
    name: str
    value: str
    position: int


@dataclass(frozen=True)
class Profile:
    """The profile a task of `kind` and `size` draws when it names none."""

    kind: str
    size: int
    profile: str


@dataclass(frozen=True)
class LaneTool:
    lane: str
    tool: str


@dataclass(frozen=True)
class Policy:
    lanes: tuple[Lane, ...] = ()
    routes: tuple[Route, ...] = ()
    exits: tuple[Exit, ...] = ()
    watches: tuple[Watch, ...] = ()
    rules: tuple[PolicyRule, ...] = ()
    vocabularies: tuple[Vocabulary, ...] = ()
    profiles: tuple[Profile, ...] = ()
    tools: tuple[LaneTool, ...] = ()


def from_files(machine: Mapping[str, Any], board: Mapping[str, Any]) -> Policy:
    """The policy the board machine document and the `[board]` settings declare."""
    states: Mapping[str, Mapping[str, Any]] = machine.get("states", {})
    return Policy(
        lanes=tuple(Lane(name, spec.get("role"), i) for i, (name, spec) in enumerate(states.items())),
        routes=tuple(
            Route(event, source, transition["to"], _condition(transition))
            for event, transitions in machine.get("events", {}).items()
            for transition in transitions
            for source in _listed(transition["from"])
        ),
        exits=tuple(
            Exit(event, writer["actor"], writer.get("trigger", ""))
            for event, writers in machine.get("writers", {}).items()
            for writer in writers
        ),
        watches=tuple(
            Watch(lane, fact, event, i)
            for lane, spec in states.items()
            for i, (fact, event) in enumerate(spec.get("waits", {}).items())
        ),
        rules=tuple(
            PolicyRule(
                i,
                guard.get("on", {}),
                guard.get("require", {}),
                str(guard.get("reason", "")).strip(),
                str(guard.get("skill", "")),
                _listed(guard.get("unless_actor", [])),
            )
            for i, guard in enumerate(board.get("guards", ()))
        ),
        vocabularies=tuple(Vocabulary("types", value, i) for i, value in enumerate(board.get("types", ()))),
        profiles=tuple(
            Profile(kind, int(size), profile)
            for kind, cells in board.get("default_profiles", {}).items()
            for size, profile in cells.items()
        ),
    )


def _listed(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def _condition(transition: Mapping[str, Any]) -> Mapping[str, Any] | None:
    rest = {key: value for key, value in transition.items() if key not in ("from", "to")}
    return rest or None
