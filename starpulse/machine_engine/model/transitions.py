"""Where an event leaves a task: one machine's transitions by event, and the Board state id a status names."""

from collections import defaultdict
from collections.abc import Collection, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotation only: the machine definition imports this module
    from starpulse.machine_engine.model.machine_definition import Writer

lazy from starpulse.contracts.adapters import Move

__all__ = [
    "ARCHIVED",
    "COMPLETED",
    "DEFAULT_STATUSES",
    "Table",
    "board_machine",
    "board_moves",
    "done_lanes",
    "lane_id",
    "tables",
]


#: Upstream's own defaults, used for a project with no `config.yml`.
DEFAULT_STATUSES = ("To Do", "In Progress", "Done")
#: The lane an archived task enters: its file keeps its status, so only the folder it sits in says it was archived.
ARCHIVED = "archived"
#: The lane a swept task enters where the Board has it: its file keeps the done status in the folder it was swept to.
COMPLETED = "completed"


def lane_id(status: str) -> str:
    """A status as the Board machine's state id: lower-cased, spaces as `_`."""
    return status.lower().replace(" ", "_")


def done_lanes(done: str) -> tuple[str, str]:
    """The lanes in which a dependency is done to its dependents: the Board's done lane `done`, or `completed`."""
    return done, COMPLETED


def board_machine(statuses: tuple[str, ...]) -> dict:
    """The Board machine a project's statuses make: a state each, and a transition between any two.

    Backlog.md lets a task move to any status, so the machine does too; `to_<state>` names the event.
    """
    ids = [lane_id(status) for status in statuses]
    return {
        "states": [
            {"id": lane_id(s), "name": s, "initial": i == 0, "final": i == len(statuses) - 1}
            for i, s in enumerate(statuses)
        ],
        "transitions": [
            {"source": source, "target": target, "event": f"to_{target}"}
            for source in ids
            for target in ids
            if source != target
        ],
        "mainLine": ids,
    }


def board_moves(
    machine: dict, writers: Mapping[str, tuple[Writer, ...]] = {}, lanes: Collection[str] | None = None
) -> dict[str, dict[str, Move]]:
    """The move verdicts out of each lane of a Board machine, by lane and then by the lane reached.

    A machine state that is not among `lanes` (a creation or archive state) is neither left nor reached; `None`
    counts every state as a lane.

    A move's writers are the actors the YAML declares for the events that make it; when any of those events
    declares none, anyone may make the move.
    """
    events: dict[tuple[str, str], list[str]] = {}
    for t in machine["transitions"]:
        if t["source"] != t["target"] and (lanes is None or {t["source"], t["target"]} <= set(lanes)):
            events.setdefault((t["source"], t["target"]), []).append(t["event"])
    moves: dict[str, dict[str, Move]] = {}
    for (source, target), names in events.items():
        declared = [writers.get(name, ()) for name in names]
        actors = () if not all(declared) else tuple(dict.fromkeys(w.actor for ws in declared for w in ws))
        moves.setdefault(source, {})[target] = Move(allowed=True, writers=actors)
    return moves


class Table:
    """One machine's transitions by event, to answer where an event leaves a task."""

    def __init__(self, machine: dict) -> None:
        self.initial = next(s["id"] for s in machine["states"] if s["initial"])
        self.finals = {s["id"] for s in machine["states"] if s["final"]}
        #: event -> source -> the states it leads to from there
        self.moves: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for t in machine["transitions"]:
            self.moves[t["event"]][t["source"]].add(t["target"])

    def place(self, current: frozenset[str], event: str, *, lenient: bool) -> frozenset[str]:
        """The states `event` leaves a task in when it may be in `current` (none: not yet placed); empty when nowhere definite.

        Either way an event a state declares leads where the machine says, and a task in a final state may
        begin again from the initial one. Strict (the replay judge) places nothing for an event no state it
        may be in declares. Lenient (the machine level) assumes the entries before it fell out of the
        stream's retention or a writer skipped a step, and places the task where the event leads from every
        other state; an event that only loops leaves it where it is. It follows one state, and none when
        several transitions leave it differently.
        """
        moves = self.moves.get(event)
        if not moves:
            return frozenset()
        here = current or frozenset({self.initial})
        if not lenient:
            return frozenset(target for _, target in self.steps(current, event))
        (state,) = here
        for source in (state, self.initial if state in self.finals else None):
            if source in moves:
                return frozenset(moves[source]) if len(moves[source]) == 1 else frozenset()
        leads = {target for source, targets in moves.items() for target in targets if target != source}
        if leads:
            return frozenset(leads) if len(leads) == 1 else frozenset()
        return here

    def steps(self, current: frozenset[str], event: str) -> frozenset[tuple[str, str]]:
        """The declared `(source, target)` pairs `event` follows from the states a task may be in (none: not yet placed);
        a task in a final state may begin again from the initial one."""
        here = current or frozenset({self.initial})
        sources = here | ({self.initial} if here & self.finals else set())
        moves = self.moves.get(event, {})
        return frozenset((source, target) for source in sources for target in moves.get(source, ()))

    def target(self, current: str | None, event: str) -> str | None:
        """Where `event` leaves a task now at `current` by the lenient rule, or None when it leaves it nowhere definite."""
        placed = self.place(frozenset({current} if current else ()), event, lenient=True)
        return next(iter(placed), None)


def tables(machines: Mapping[str, dict]) -> dict[str, Table]:
    """A table for each machine the page draws, the Board excepted: its tasks come from the projection."""
    return {name: Table(machine) for name, machine in machines.items() if name != "board"}
