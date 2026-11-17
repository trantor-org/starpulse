"""The Board writer's held snapshot: built whole once, then each change the feed publishes is folded into it.

A side field (pulls, claims, dags, the ledger marks) is replaced from its change's own payload, a `snapshot` change
and a local midnight build the snapshot whole again, and the writer's clock tick (`TICK`) ages what time alone moves:
the machine window and the merge strip. A rating is announced by no change, so every fold reads it again.

A task delta re-reads its Task through the whole build's query (`drawn_task`), not from the delta's own agent: a
guarded move, the Definition of Done and the readable verdict differ between the two, and the held snapshot must equal
a whole build. Each fold replaces the snapshot and the objects it changes and edits none, so a reader keeps the one it has.
"""

import logging
import queue
import time
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from starpulse.board.model.feed.shared import local_midnight
from starpulse.event_log.wake import StopEvent
from starpulse.machine_engine.model.machine_ties import derive

if TYPE_CHECKING:
    from starpulse.board.model.board_feed import BoardFeed

logger = logging.getLogger(__name__)

#: The most seconds the writer lets pass before it ages the time-bound fields.
TICK = 30.0

#: The kinds of change the fold takes; `tick` is the writer's clock.
FOLDS = frozenset({"task", "move", "pulls", "claim", "dags", "ledgers", "snapshot", "tick"})
#: The change that updates each snapshot key; `build` is a key the writer's whole build holds, which no change moves.
#: `ratings` is read again from the feed on every fold, because a rating is appended with no change to announce it.
RULES: dict[str, tuple[str, ...]] = {
    "flows": ("task", "move", "snapshot", "tick"),
    "machinePage": ("move", "snapshot", "tick"),
    "machineStrip": ("task", "move", "snapshot", "tick"),
    "settled": ("task", "snapshot"),
    "cold_done": ("task", "snapshot"),
    "milestone_done": ("task", "snapshot", "tick"),
    "archived_today": ("task", "snapshot", "tick"),
    "now": ("task", "move", "pulls", "claim", "dags", "ledgers", "tick"),
    "ratings": ("task", "move", "pulls", "claim", "dags", "ledgers", "tick"),
    "pulls": ("pulls", "snapshot"),
    "claims": ("claim", "snapshot"),
    "dags": ("dags", "snapshot"),
    "pools": ("dags", "snapshot"),
    "cpu": ("dags", "snapshot"),
    "error": ("dags", "snapshot"),
    "mergeStrip": ("ledgers", "snapshot", "tick"),
    "mergePins": ("ledgers", "snapshot", "tick"),
    "domains": ("snapshot",),
    "cues": ("snapshot",),
    "reading": ("snapshot",),
    "graphs": ("build",),
    "roles": ("build",),
    "capabilities": ("build",),
    "interactive": ("build",),
    "boardUrl": ("build",),
}


class HeldSnapshot:
    def __init__(self, feed: "BoardFeed", clock: Callable[[], float] = time.time) -> None:
        self._feed, self._clock = feed, clock
        self._changes = feed.follow_changes()  # before `build`, so a change it overlaps is folded again, and ends the same
        self._heads: list[tuple[str, Any]] = []
        self._lanes: dict[str, dict[str, dict]] = {}
        self._cold: dict[str, str] = {}
        self._day = 0.0
        self.snapshot: dict[str, Any] = {}

    def build(self) -> None:
        """Take the snapshot whole, and the lanes and cold Done Tasks it is folded from."""
        self._cold = self._feed.cold_done()
        snapshot = self._feed.snapshot()
        self._heads = [(flow["name"], flow["machine"]) for flow in snapshot["flows"]]
        self._lanes = {flow["name"]: {agent["id"]: agent for agent in flow["agents"]} for flow in snapshot["flows"]}
        self._day = local_midnight(self._clock())
        self.snapshot = snapshot

    def run(self, stop: StopEvent) -> None:
        """Build the snapshot, then fold each change as it is published and a tick every `TICK`, until `stop`."""
        stop.listen(lambda: self._changes.put(None))  # type: ignore[arg-type]
        self.build()
        due = time.monotonic() + TICK  # a deadline, so a steady run of changes cannot keep the tick off
        while not stop.is_set():
            try:
                change = self._changes.get(timeout=max(0.0, due - time.monotonic()))
            except queue.Empty:
                change = None
            if change is not None:
                self._folded(*change)
            if time.monotonic() >= due:
                self._folded("tick", {})
                due = time.monotonic() + TICK

    def _folded(self, kind: str, data: dict) -> None:
        try:
            self.fold(kind, data)
        except Exception:
            logger.exception("StarPulse: the held snapshot could not fold a %s change; it is built again", kind)
            self.build()

    def fold(self, kind: str, data: dict) -> None:
        """Fold a change of one of `FOLDS`; any other kind feeds no snapshot key and changes nothing."""
        if kind not in FOLDS:
            return
        if kind == "snapshot" or local_midnight(self._clock()) != self._day:
            return self.build()
        fields: dict[str, Any] = {}
        if kind == "task":
            self._task(data["id"])
        elif kind == "move":
            if data["machine"] in self._lanes:
                self._lanes[data["machine"]][data["id"]] = data["agent"]
        elif kind == "pulls":
            fields = {"pulls": data["pulls"]}
        elif kind == "claim":
            fields = {"claims": {**self.snapshot["claims"], data["task"]: {"reason": data["reason"], "at": data["at"]}}}
        elif kind == "dags":
            fields = {key: data[key] for key in ("dags", "pools", "cpu", "error")}
        elif kind == "ledgers":
            fields = {key: data[key] for key in ("mergeStrip", "mergePins")}
        else:
            self._age()
            fields = self._feed.ledger_marks()
        self._publish(data.get("archived_today") if kind == "task" else None, fields)

    def _age(self) -> None:
        """Drop the machine tasks the window has moved past, as a whole build reads only those placed inside it."""
        window = self._feed.window_s
        if window is not None:
            since = self._clock() - window
            for name, _ in self._heads:
                if name != "board":
                    self._lanes[name] = {key: agent for key, agent in self._lanes[name].items() if agent["active"] >= since}

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

    def _publish(self, archived_today: int | None, fields: dict[str, Any]) -> None:
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
            "ratings": self._feed.ratings(),
            **fields,
            "now": now,
        }
