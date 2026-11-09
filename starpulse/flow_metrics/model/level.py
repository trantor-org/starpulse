"""The `[level]` config block: a flow graph one level above the Board, configured rather than hard-coded.

A level reads the trajectories of one Board machine, merged across sources. It names the machine, the `goal` state it
is judged by, the policy `gates` every run should cross, every way a run ends (`terminals`, each with a role), what
its orbit view circles (`orbit`), the `facets` a viewer groups and filters by, and how activity replays (`activity`).
`parse_level` reads the table and `Level.check` holds it to the states of the machine it names; `Level.filter` selects runs
by facet.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["Activity", "Facet", "Level", "LevelError", "Orbit", "Terminal", "parse_level"]

SUNS = ("terminal", "working")
MEASURES = ("share", "count", "flux")
PACES = ("live", "min", "fast")

_KEYS = {"machine", "goal", "gates", "terminals", "orbit", "facets", "activity", "title", "subject", "runs", "series"}


class LevelError(ValueError):
    """The level cannot be drawn as configured; the message names what to change."""


@dataclass(frozen=True)
class Terminal:
    """One way a run ends: its machine state and the role it plays (`goal`, `abandoned`, or another outcome to watch)."""

    id: str
    role: str


@dataclass(frozen=True)
class Orbit:
    """What the orbit view circles: `terminal` states, or the `working` states listed here."""

    suns: str = "terminal"
    working: tuple[str, ...] = ()


@dataclass(frozen=True)
class Facet:
    """A field a viewer groups and filters runs by; `label` is what the page calls it."""

    id: str
    label: str


@dataclass(frozen=True)
class Activity:
    """How activity aggregates into dots (`measure`) and how fast the page replays it (`pace`)."""

    measure: str = "share"
    pace: str = "min"


@dataclass(frozen=True)
class Level:
    machine: str
    goal: str
    terminals: tuple[Terminal, ...]
    gates: tuple[str, ...] = ()
    orbit: Orbit = Orbit()
    facets: tuple[Facet, ...] = ()
    activity: Activity = Activity()
    title: str = "Flow graph"
    subject: str = "task"
    runs: str = "runs"
    series: str | None = None

    def check(self, machines: Mapping[str, Mapping[str, Any]]) -> None:
        """Refuse a level whose machine the board does not draw, or whose goal, gates, terminals or working states
        name a state that machine lacks."""
        if (machine := machines.get(self.machine)) is None:
            raise LevelError(f"level: machine {self.machine} is not one the board draws")
        states = {state["id"] for state in machine["states"]}
        named = (
            [("goal", self.goal)]
            + [("gate", gate) for gate in self.gates]
            + [("terminal", terminal.id) for terminal in self.terminals]
            + [("orbit.working", state) for state in self.orbit.working]
        )
        for where, state in named:
            if state not in states:
                raise LevelError(f"level: {where} {state} is not a state of machine {self.machine}")

    def filter[R](
        self, runs: Iterable[R], select: Mapping[str, Collection[str]], facets_of: Callable[[R], Mapping[str, str]]
    ) -> list[R]:
        """The runs whose value of every selected facet is among its selected values.

        A run that has no value for a selected facet is excluded, never counted as zero or as an empty value; an empty
        selection keeps every run.
        """
        configured = {facet.id for facet in self.facets}
        if unknown := sorted(select.keys() - configured):
            raise LevelError(f"level: facet {unknown[0]} is not configured")
        kept = []
        for run in runs:
            facets = facets_of(run)
            if all(facet in facets and facets[facet] in values for facet, values in select.items()):
                kept.append(run)
        return kept


def parse_level(raw: object) -> Level:
    """The level the `[level]` table `raw` configures; a table the schema refuses raises `LevelError`."""
    if not isinstance(raw, dict):
        raise LevelError("level must be a [level] table")
    if unknown := sorted(raw.keys() - _KEYS):
        raise LevelError(f"level: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_KEYS))}")
    for key in ("machine", "goal", "terminals"):
        if key not in raw:
            raise LevelError(f"level needs {key}")
    machine, goal = _text(raw, "machine"), _text(raw, "goal")
    terminals = _terminals(raw["terminals"])
    if goal not in {terminal.id for terminal in terminals}:
        raise LevelError(f"level: goal {goal} is not one of the level's terminals")
    orbit = _orbit(raw.get("orbit", {}), terminals)
    texts = {key: _text(raw, key) for key in ("title", "subject", "runs", "series") if key in raw}
    return Level(
        machine,
        goal,
        terminals,
        gates=_names(raw.get("gates", []), "gates"),
        orbit=orbit,
        facets=_facets(raw.get("facets", [])),
        activity=_activity(raw.get("activity", {})),
        **texts,
    )


def _text(table: Mapping[str, Any], key: str, where: str = "level") -> str:
    value = table[key]
    if not isinstance(value, str) or not value:
        raise LevelError(f"{where}: {key} must be non-empty text")
    return value


def _names(value: object, what: str) -> tuple[str, ...]:
    if not (isinstance(value, list) and all(isinstance(name, str) and name for name in value)):
        raise LevelError(f"level: {what} must be a list of state names")
    return tuple(value)


def _tables(value: object, what: str) -> list[dict[str, Any]]:
    if not (isinstance(value, list) and all(isinstance(entry, dict) for entry in value)):
        raise LevelError(f"level: {what} must be a list of tables")
    return value


def _terminals(value: object) -> tuple[Terminal, ...]:
    terminals: list[Terminal] = []
    for entry in _tables(value, "terminals"):
        if unknown := sorted(entry.keys() - {"id", "role"}):
            raise LevelError(f"level: terminal has unknown key(s) {', '.join(unknown)}; known: id, role")
        if "id" not in entry:
            raise LevelError("level: a terminal needs an id")
        terminal = _text(entry, "id", "level: terminal")
        if "role" not in entry:
            raise LevelError(f"level: terminal {terminal} needs a role")
        if any(terminal == earlier.id for earlier in terminals):
            raise LevelError(f"level: terminal {terminal} is listed twice")
        terminals.append(Terminal(terminal, _text(entry, "role", f"level: terminal {terminal}")))
    if not terminals:
        raise LevelError("level needs terminals")
    return tuple(terminals)


def _orbit(value: object, terminals: tuple[Terminal, ...]) -> Orbit:
    if not isinstance(value, dict):
        raise LevelError("level: orbit must be a [level.orbit] table")
    if unknown := sorted(value.keys() - {"suns", "working"}):
        raise LevelError(f"level: orbit has unknown key(s) {', '.join(unknown)}; known: suns, working")
    suns = value.get("suns", "terminal")
    if suns not in SUNS:
        raise LevelError(f"level: orbit.suns must be terminal or working, not {suns!r}")
    working = _names(value.get("working", []), "orbit.working")
    if suns == "working" and not working:
        raise LevelError("level: orbit.working must name a working state when orbit.suns is working")
    if ended := next((state for state in working if state in {terminal.id for terminal in terminals}), None):
        raise LevelError(f"level: orbit.working state {ended} is a terminal, not a working state")
    return Orbit(suns, working)


def _facets(value: object) -> tuple[Facet, ...]:
    facets: list[Facet] = []
    for entry in _tables(value, "facets"):
        if unknown := sorted(entry.keys() - {"id", "label"}):
            raise LevelError(f"level: a facet has unknown key(s) {', '.join(unknown)}; known: id, label")
        if "id" not in entry:
            raise LevelError("level: a facet needs an id")
        facet = _text(entry, "id", "level: facet")
        if any(facet == earlier.id for earlier in facets):
            raise LevelError(f"level: facet {facet} is listed twice")
        facets.append(Facet(facet, _text(entry, "label", f"level: facet {facet}") if "label" in entry else facet))
    return tuple(facets)


def _activity(value: object) -> Activity:
    if not isinstance(value, dict):
        raise LevelError("level: activity must be a [level.activity] table")
    if unknown := sorted(value.keys() - {"measure", "pace"}):
        raise LevelError(f"level: activity has unknown key(s) {', '.join(unknown)}; known: measure, pace")
    measure, pace = value.get("measure", "share"), value.get("pace", "min")
    if measure not in MEASURES:
        raise LevelError(
            f"level: activity.measure must be {', '.join(MEASURES[:-1])} or {MEASURES[-1]}, not {measure!r}"
        )
    if pace not in PACES:
        raise LevelError(f"level: activity.pace must be {', '.join(PACES[:-1])} or {PACES[-1]}, not {pace!r}")
    return Activity(measure, pace)
