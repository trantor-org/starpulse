"""Recorded moves judged against the machine they were made on.

A machine as the page draws it (`snapshot.describe`) has states and transitions but no extended state, so a move is
judged by its shape: legal when some transition leads from the lane it left to the lane it entered. A guard that reads
a task's facts is not judged, because the history keeps none.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from starpulse.machine_engine.model.transitions import Table

#: How many example tasks a violation names.
EXAMPLES = 5


@dataclass(frozen=True)
class Violation:
    """Every undeclared move from `source` to `move` (a lane, or an event), with up to `EXAMPLES` tasks that made one."""

    source: str
    move: str
    count: int
    tasks: tuple[str, ...]


@dataclass(frozen=True)
class Report:
    """What replaying one machine's history judged: `replayed` moves and the `violations` among them."""

    machine: str
    replayed: int
    violations: tuple[Violation, ...]


def initial(machine: dict) -> str:
    return next(state["id"] for state in machine["states"] if state["initial"])


def lane_moves(machine: dict) -> set[tuple[str, str]]:
    """The `(source, target)` pairs some transition of the machine leads along."""
    return {(t["source"], t["target"]) for t in machine["transitions"]}


def check_lanes(name: str, machine: dict, rows: Iterable[tuple[str, float, str | None, str]]) -> Report:
    """Judge `(task, at, from, to)` lane changes, oldest first; a task's first has no `from` and leaves the initial state.

    A row that stays in its lane is not a move and is not counted."""
    declared = lane_moves(machine)
    start = initial(machine)
    replayed = 0
    refused: dict[tuple[str, str], list[str]] = defaultdict(list)
    for task, _, source, target in rows:
        source = source or start
        if source == target:
            continue
        replayed += 1
        if (source, target) not in declared:
            refused[source, target].append(task)
    return Report(
        name, replayed, tuple(Violation(s, t, len(tasks), _examples(tasks)) for (s, t), tasks in refused.items())
    )


def _examples(tasks: list[str]) -> tuple[str, ...]:
    """The first `EXAMPLES` distinct tasks, in the order they first made the move."""
    return tuple(dict.fromkeys(tasks))[:EXAMPLES]


class EventJudge:
    """One machine's events judged key by key (a task or a run), each from the initial state.

    An event several transitions share leaves the key in any state it leads to, so the key's possible states are tracked,
    and a key in a final state may also begin again from the initial one."""

    def __init__(self, table: Table) -> None:
        self._table = table
        self._where: dict[str, frozenset[str]] = {}

    def judge(self, key: str, event: str) -> str | None:
        """Apply `event` to `key`: None when a state it may be in declares the event, else those states joined with `|`.

        The event a state does not declare leaves the key where it was."""
        here = self._where.setdefault(key, frozenset({self._table.initial}))
        if leads := self._table.place(here, event, lenient=False):
            self._where[key] = leads
            return None
        return " | ".join(sorted(here))


def check_events(name: str, machine: dict, rows: Iterable[tuple[str, float, str]]) -> Report:
    """Judge `(key, at, event)` rows, oldest first, each key replayed on its own from the initial state."""
    judge = EventJudge(Table(machine))
    replayed = 0
    refused: dict[tuple[str, str], list[str]] = defaultdict(list)
    for key, _, event in rows:
        replayed += 1
        if (source := judge.judge(key, event)) is not None:
            refused[source, event].append(key)
    return Report(
        name, replayed, tuple(Violation(s, e, len(keys), _examples(keys)) for (s, e), keys in refused.items())
    )
