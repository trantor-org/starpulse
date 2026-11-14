"""The board's policy as rows: its lanes, the routes between them, who takes each exit, the facts each lane watches, the
rules a write must meet, the vocabularies and the profile cells.

The lanes, routes, exits and vocabularies still have a file source, the board machine (`states`, `events`, `writers`) and
`starpulse.toml`'s `[board] types`: `from_files` reads them into a `Policy`, and a store that holds none is governed by
them until a migration fills the tables. The rules, watches and profiles live only in the tables.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "Exit",
    "Lane",
    "LaneTool",
    "Policy",
    "PolicyRule",
    "Profile",
    "Route",
    "Vocabulary",
    "Watch",
    "from_files",
    "guards_of",
    "profile_matrix",
    "refuse_retired",
    "waits_of",
]


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


#: The `[board]` keys the policy DB replaced, each as the config spells it.
RETIRED = {"guards": "[[board.guards]]", "rules": "[[board.rules]]", "default_profiles": "[board.default_profiles]"}


def refuse_retired(board: Mapping[str, Any]) -> None:
    """Raise ValueError naming the policy DB when `board` still declares policy the DB now holds."""
    if declared := [spelled for key, spelled in RETIRED.items() if key in board]:
        raise ValueError(
            f"board: {', '.join(declared)} no longer read: board policy lives in the policy DB "
            "(`starpulse policy show` prints it; `starpulse policy revision` changes it)"
        )


def guards_of(policy: Policy) -> list[dict[str, Any]]:
    """The policy's rules as the tables `board.rules.load` reads, in position order."""
    return [
        {"on": r.on, "require": r.require, "reason": r.reason, "skill": r.skill, "unless_actor": r.unless_actor}
        for r in sorted(policy.rules, key=lambda rule: rule.position)
    ]


def waits_of(policy: Policy) -> dict[str, dict[str, str]]:
    """Each lane's watched facts as `{lane: {fact: event}}`, the first fact holding winning."""
    waits: dict[str, dict[str, str]] = {}
    for watch in sorted(policy.watches, key=lambda w: (w.lane, w.position)):
        waits.setdefault(watch.lane, {})[watch.fact] = watch.event
    return waits


def profile_matrix(policy: Policy) -> dict[str, dict[str, str]]:
    """The profile cells as `{kind: {size: profile}}`, the shape `board.entry.load` fills a task's profile from."""
    matrix: dict[str, dict[str, str]] = {}
    for cell in policy.profiles:
        matrix.setdefault(cell.kind, {})[str(cell.size)] = cell.profile
    return matrix


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
        vocabularies=tuple(Vocabulary("types", value, i) for i, value in enumerate(board.get("types", ()))),
    )


def _listed(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def _condition(transition: Mapping[str, Any]) -> Mapping[str, Any] | None:
    rest = {key: value for key, value in transition.items() if key not in ("from", "to")}
    return rest or None
