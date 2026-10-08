"""Where an event leaves a task: one machine's transitions by event, and the Board state id a status names."""

from collections import defaultdict
from collections.abc import Mapping

__all__ = ["Table", "lane_id", "tables"]


def lane_id(status: str) -> str:
    """A status as the Board machine's state id: lower-cased, spaces as `_`."""
    return status.lower().replace(" ", "_")


class Table:
    """One machine's transitions by event, to answer where an event leaves a task."""

    def __init__(self, machine: dict) -> None:
        self.initial = next(s["id"] for s in machine["states"] if s["initial"])
        self.finals = {s["id"] for s in machine["states"] if s["final"]}
        #: event -> source -> the states it leads to from there
        self.moves: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for t in machine["transitions"]:
            self.moves[t["event"]][t["source"]].add(t["target"])

    def target(self, current: str | None, event: str) -> str | None:
        """Where `event` leaves a task now at `current` (None: not yet placed), or None when it leaves it nowhere definite.

        An event the state allows leads where the machine says, and a task in a final state begins
        again from the initial one. An event the state does not allow, because the entries before it
        fell out of the stream's retention or a writer skipped a step, places the task where the event
        leads from every other state; an event that only loops leaves it where it is.
        """
        moves = self.moves.get(event)
        if not moves:
            return None
        current = current or self.initial
        for source in (current, self.initial if current in self.finals else None):
            if source in moves:
                return next(iter(moves[source])) if len(moves[source]) == 1 else None
        leads = {target for source, targets in moves.items() for target in targets if target != source}
        if leads:
            return next(iter(leads)) if len(leads) == 1 else None
        return current


def tables(machines: Mapping[str, dict]) -> dict[str, Table]:
    """A table for each machine the page draws, the Board excepted: its tasks come from the projection."""
    return {name: Table(machine) for name, machine in machines.items() if name != "board"}
