"""The Board writer's held snapshot: built whole once, then each task and machine move is folded into it.

A task delta re-reads its Task through the whole build's query (`drawn_task`), not from the delta's own agent: a
guarded move, the Definition of Done and the readable verdict differ between the two, and the held snapshot must equal
a whole build. Each fold replaces the snapshot and the objects it changes and edits none, so a reader keeps the one it has.
"""

import logging
import time
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from starpulse.event_log.wake import StopEvent
from starpulse.machine_engine.model.machine_ties import derive

if TYPE_CHECKING:
    from starpulse.board.model.board_feed import BoardFeed

logger = logging.getLogger(__name__)

#: The snapshot keys a `task` or `move` delta updates (`settled` and `cold_done` stay empty with a read model, which
#: counts the Done Tasks off the board in `milestone_done`), and `now`, which each fold stamps.
FOLDED = frozenset(
    {"flows", "machinePage", "machineStrip", "settled", "cold_done", "milestone_done", "archived_today", "now"}
)
#: The keys no fold updates yet: the build's value stands until the side fields and the clock fold (TASK-15119).
SIDE = frozenset(
    {
        "graphs", "ratings", "dags", "pools", "cpu", "pulls", "mergeStrip", "mergePins", "claims", "roles",
        "capabilities", "interactive", "error", "reading", "cues", "domains", "boardUrl",
    }
)  # fmt: skip


class HeldSnapshot:
    def __init__(self, feed: "BoardFeed", clock: Callable[[], float] = time.time) -> None:
        self._feed, self._clock = feed, clock
        self._changes = feed.follow_changes()  # before `build`, so a change it overlaps is folded again, and ends the same
        self._heads: list[tuple[str, Any]] = []
        self._lanes: dict[str, dict[str, dict]] = {}
        self._cold: dict[str, str] = {}
        self.snapshot: dict[str, Any] = {}

    def build(self) -> None:
        """Take the snapshot whole, and the lanes and cold Done Tasks it is folded from."""
        self._cold = self._feed.cold_done()
        snapshot = self._feed.snapshot()
        self._heads = [(flow["name"], flow["machine"]) for flow in snapshot["flows"]]
        self._lanes = {flow["name"]: {agent["id"]: agent for agent in flow["agents"]} for flow in snapshot["flows"]}
        self.snapshot = snapshot

    def run(self, stop: StopEvent) -> None:
        """Build the snapshot, then fold each change as it is published, until `stop`."""
        stop.listen(lambda: self._changes.put(None))  # type: ignore[arg-type]
        self.build()
        while not stop.is_set():
            change = self._changes.get()
            if change is not None:
                self._folded(*change)

    def _folded(self, kind: str, data: dict) -> None:
        try:
            self.fold(kind, data)
        except Exception:
            logger.exception("StarPulse: the held snapshot could not fold a %s change; it is built again", kind)
            self.build()

    def fold(self, kind: str, data: dict) -> None:
        """Fold a `task` or `move` delta; any other kind is a side field's (`SIDE`) and changes nothing yet."""
        if kind == "task":
            self._task(data["id"])
        elif kind == "move":
            if data["machine"] in self._lanes:
                self._lanes[data["machine"]][data["id"]] = data["agent"]
        else:
            return
        self._publish(data.get("archived_today") if kind == "task" else None)

    def _task(self, task_id: str) -> None:
        """Draw the Task again, and each Board Task that depends on it (whose workable flag and moves rest on it)."""
        board = self._lanes["board"]
        dependents = [other for other, agent in board.items() if task_id in agent.get("dependencies", ())]
        for drawn in (task_id, *dependents):
            agent, milestone = self._feed.drawn_task(drawn)
            for held, value in ((board, agent), (self._cold, milestone)):
                if value is None:
                    held.pop(drawn, None)
                else:
                    held[drawn] = value

    def _publish(self, archived_today: int | None) -> None:
        now = self._clock()
        flows = [
            {"name": name, "machine": machine, "agents": [self._lanes[name][key] for key in sorted(self._lanes[name])]}
            for name, machine in self._heads
        ]
        derived = derive(flows, now)
        self.snapshot = {
            **self.snapshot,
            "flows": [{**flow, **derived.get(flow["name"], {})} for flow in flows],
            **self._feed.machine_fields(flows, derived, now),
            "milestone_done": dict(sorted(Counter(self._cold.values()).items())),
            "archived_today": self.snapshot["archived_today"] if archived_today is None else archived_today,
            "now": now,
        }
