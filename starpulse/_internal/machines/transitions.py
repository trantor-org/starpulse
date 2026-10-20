"""Where an event leaves a task: one machine's transitions by event, and the Board state id a status names."""

from collections import defaultdict
from collections.abc import Mapping

__all__ = ["DEFAULT_STATUSES", "DONE", "Table", "WAITING", "board_machine", "lane_id", "tables"]


#: Upstream's own defaults, used for a project with no `config.yml`.
DEFAULT_STATUSES = ("To Do", "In Progress", "Done")
#: The lanes a task's workability reads: it can wait on Start Criteria in one, and a dependency is done in the other.
WAITING, DONE = "waiting", "done"


def lane_id(status: str) -> str:
    """A status as the Board machine's state id: lower-cased, spaces as `_`."""
    return status.lower().replace(" ", "_")


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
        sources = here | ({self.initial} if here & self.finals else set())
        if not lenient:
            return frozenset(target for source in sources for target in moves.get(source, ()))
        (state,) = here
        for source in (state, self.initial if state in self.finals else None):
            if source in moves:
                return frozenset(moves[source]) if len(moves[source]) == 1 else frozenset()
        leads = {target for source, targets in moves.items() for target in targets if target != source}
        if leads:
            return frozenset(leads) if len(leads) == 1 else frozenset()
        return here

    def target(self, current: str | None, event: str) -> str | None:
        """Where `event` leaves a task now at `current` by the lenient rule, or None when it leaves it nowhere definite."""
        placed = self.place(frozenset({current} if current else ()), event, lenient=True)
        return next(iter(placed), None)


def tables(machines: Mapping[str, dict]) -> dict[str, Table]:
    """A table for each machine the page draws, the Board excepted: its tasks come from the projection."""
    return {name: Table(machine) for name, machine in machines.items() if name != "board"}
