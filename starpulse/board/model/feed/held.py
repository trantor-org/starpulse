"""The Board writer's held snapshot: built whole once, then each change the feed publishes is folded into it.

A side field (pulls, claims, dags, the ledger marks) is replaced from its change's own payload, a `snapshot` change
and a local midnight build the snapshot whole again, and the writer's clock tick (`TICK`) ages what time alone moves:
the machine window and the merge strip. A rating is announced by no change, so every fold reads it again.

A task delta re-reads its Task through the whole build's query (`drawn_task`), not from the delta's own agent: a
guarded move, the Definition of Done and the readable verdict differ between the two, and the held snapshot must equal
a whole build. Each fold replaces the snapshot and the objects it changes and edits none, so a reader keeps the one it has.

With a `store`, each fold saves the changes it took as deltas and the encoded bodies with them, except that a fold of
only machine moves and ticks (`HELD_BACK`), which come several a second, stores its bodies at most every `SAVE_EVERY`:
a body is megabytes to encode, and an event stream replays the deltas past it. A write reads back at once. A body held
back is stored once the interval ends, when the deltas behind it near the store's window, or when `caught_up` asks.
"""

import logging
import queue
import threading
import time
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from starpulse.board.model.feed.shared import local_midnight
from starpulse.event_log.readmodel.snapshot_store import SnapshotStore
from starpulse.event_log.wake import StopEvent
from starpulse.machine_engine.model.machine_ties import derive

if TYPE_CHECKING:
    from starpulse.board.model.board_feed import BoardFeed

logger = logging.getLogger(__name__)

#: The most seconds the writer lets pass before it ages the time-bound fields.
TICK = 30.0
#: The changes whose bodies wait for `SAVE_EVERY`: a machine lane's move and the clock, which no write reads back.
HELD_BACK = frozenset({"move", "tick"})
#: The fewest seconds between two stores of the bodies of `HELD_BACK` folds.
SAVE_EVERY = 10.0
#: What `caught_up` puts on the queue to have `run` store a body held back.
_FLUSH = ("flush", {})

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
    "interactive": ("task", "move", "pulls", "claim", "dags", "ledgers", "tick"),
    "boardUrl": ("build",),
}


class HeldSnapshot:
    def __init__(
        self, feed: "BoardFeed", clock: Callable[[], float] = time.time, store: SnapshotStore | None = None
    ) -> None:
        self._feed, self._clock, self._store = feed, clock, store
        self._stored: dict[str, Any] | None = None  # the snapshot the store holds
        self._unsaved: list[tuple[str, dict]] = []  # the changes a failed save left
        self._behind = 0  # the deltas stored after the stored body
        self._body_due = float("-inf")  # when, by `clock`, the next body may be stored
        self._changes = feed.follow_changes()  # before `build`, so a change it overlaps is folded again, and ends the same
        self._heads: list[tuple[str, Any]] = []
        self._lanes: dict[str, dict[str, dict]] = {}
        self._cold: dict[str, str] = {}
        self._day = 0.0
        self._stale = False
        self._folding = False  # whether `run` takes the queue
        self._storing = threading.Lock()  # the one store at a time: `retire` runs on the thread that stops the writer
        self._retired = False
        self.snapshot: dict[str, Any] = {}
        #: Set once the first build is stored (or failed): `run` then folds changes.
        self.started = threading.Event()

    def build(self) -> None:
        """Take the snapshot whole, and the lanes and cold Done Tasks it is folded from."""
        self._cold = self._feed.cold_done()
        snapshot = self._feed.snapshot()
        self._heads = [(flow["name"], flow["machine"]) for flow in snapshot["flows"]]
        self._lanes = {flow["name"]: {agent["id"]: agent for agent in flow["agents"]} for flow in snapshot["flows"]}
        self._day = local_midnight(self._clock())
        self.snapshot = snapshot
        self._stale = False

    def run(self, stop: StopEvent) -> None:
        """Build the snapshot and store it as a `snapshot` delta (a stream attached before the start missed what changed while
        the writer was down, in no stored delta), then fold the changes published since each publish as one, and a tick
        every `TICK`, until `stop`."""
        stop.listen(lambda: self._changes.put(None))  # type: ignore[arg-type]
        try:
            self._rebuilt([], restarted=True)
            self.started.set()
            self._folding = True
            due = time.monotonic() + TICK  # a deadline, so a steady run of changes cannot keep the tick off
            while not stop.is_set():
                wait = due - time.monotonic()
                if self._held_back():
                    wait = min(wait, self._body_due - self._clock())
                try:
                    batch = [self._changes.get(timeout=max(0.0, wait))]
                except queue.Empty:
                    batch = []
                while not self._changes.empty():
                    batch.append(self._changes.get_nowait())
                changes = [change for change in batch if change is not None and change is not _FLUSH]
                if time.monotonic() >= due:
                    changes.append(("tick", {}))
                    due = time.monotonic() + TICK
                if changes:
                    self._folded(changes)
                if self._held_back() and (any(change is _FLUSH for change in batch) or self._clock() >= self._body_due):
                    self._save([], force=True)
                    if self._held_back():  # the store refused it: try again after the interval, not at once
                        self._body_due = self._clock() + SAVE_EVERY
                for _ in batch:
                    self._changes.task_done()
        finally:
            self._folding = False
            self._feed.unsubscribe(self._changes)

    def caught_up(self, timeout: float) -> bool:
        """Whether every change the feed published is folded into the snapshot and, with a store, stored, waiting up to
        `timeout` for the ones not. A fold or save that failed is not caught up: the queue drains either way. While `run`
        folds, a body the interval holds back is stored now."""
        deadline = time.monotonic() + timeout
        drained = self._drained(timeout)
        if drained and self._folding and self._held_back():
            self._changes.put(_FLUSH)  # type: ignore[arg-type]
            drained = self._drained(max(0.0, deadline - time.monotonic()))
        return drained and not self._stale and not self._unsaved and not self._held_back()

    def _drained(self, timeout: float) -> bool:
        with self._changes.all_tasks_done:
            return self._changes.all_tasks_done.wait_for(lambda: not self._changes.unfinished_tasks, timeout)

    def _held_back(self) -> bool:
        return self._store is not None and not self._stale and self.snapshot is not self._stored

    def _rebuilt(self, changes: list[tuple[str, dict]], restarted: bool = False) -> None:
        try:
            self.build()
        except Exception:
            logger.exception("StarPulse: the held snapshot could not be built; it is built again on the next change or tick")
            self._stale = True
            if self._store is not None:
                self._unsaved += changes
            return
        self._save([("snapshot", self.snapshot)] if restarted else changes, force=restarted)

    def _folded(self, changes: list[tuple[str, dict]]) -> None:
        try:
            if self._stale:
                self.build()
            self.fold_all(changes)
        except Exception:
            logger.exception("StarPulse: the held snapshot could not fold %d changes; it is built again", len(changes))
            self._rebuilt(changes)

    def retire(self) -> None:
        """Store that no writer folds from here on, as the last delta this writer stores, so a stream open tells its page
        the Board is stale until a writer stores again (`snapshot` is the first delta a started writer stores). The stored
        body keeps its sequence: it reflects what was folded. Runs on the thread that stops the writer, which the held
        snapshot's own thread may not outlive; a crash stores none."""
        with self._storing:
            if self._store is None or self._retired:
                return
            self._retired = True
            try:
                self._store.save([("stale", {"at": self._clock()})], None, self._clock(), current=False)
            except Exception:
                logger.exception("StarPulse: the held snapshot could not store that its writer stopped")

    def _save(self, changes: list[tuple[str, dict]], force: bool = False) -> None:
        with self._storing:
            if not self._retired:
                self._store_changes(changes, force)

    def _store_changes(self, changes: list[tuple[str, dict]], force: bool) -> None:
        """Store every change taken since the last save, and the snapshot when it is not the one stored and `force`, a
        change outside `HELD_BACK`, the interval or the store's window says so. A save that fails is logged and its changes
        go with the next."""
        if self._store is None:
            return
        self._unsaved += changes
        changed = self._held_back()
        behind = self._behind + len(self._unsaved)
        written = any(kind in FOLDS - HELD_BACK for kind, _ in self._unsaved)
        body = changed and (force or written or self._clock() >= self._body_due or behind >= self._store.keep // 2)
        if not self._unsaved and not body:
            return
        try:
            self._store.save(self._unsaved, self.snapshot if body else None, self._clock(), current=not changed)
        except Exception:
            logger.exception("StarPulse: the held snapshot could not be stored; it is stored with the next fold")
            return
        self._unsaved, self._behind = [], 0 if body else behind
        if body:
            self._stored, self._body_due = self.snapshot, self._clock() + SAVE_EVERY

    def fold(self, kind: str, data: dict) -> None:
        self.fold_all([(kind, data)])

    def fold_all(self, changes: list[tuple[str, dict]]) -> None:
        """Fold changes of `FOLDS` in order, then publish once: a publish derives every flow, so one per change starves a
        start that finds hundreds. Any other kind feeds no snapshot key and changes nothing."""
        fields: dict[str, Any] = {}
        archived_today, folded = None, False
        for kind, data in changes:
            if kind not in FOLDS:
                continue
            if kind == "snapshot" or local_midnight(self._clock()) != self._day:
                self.build()
                fields, archived_today, folded = {}, None, False
                continue
            self._apply(kind, data, fields)
            if kind == "task" and data.get("archived_today") is not None:
                archived_today = data["archived_today"]
            folded = True
        if folded:
            self._publish(archived_today, fields)
        self._save(changes)

    def _apply(self, kind: str, data: dict, fields: dict[str, Any]) -> None:
        if kind == "task":
            self._task(data["id"])
        elif kind == "move":
            if data["machine"] in self._lanes:
                self._lanes[data["machine"]][data["id"]] = data["agent"]
        elif kind == "pulls":
            fields["pulls"] = data["pulls"]
        elif kind == "claim":
            claims = fields.get("claims", self.snapshot["claims"])
            fields["claims"] = {**claims, data["task"]: {"reason": data["reason"], "at": data["at"]}}
        elif kind == "dags":
            fields.update({key: data[key] for key in ("dags", "pools", "cpu", "error")})
        elif kind == "ledgers":
            fields.update({key: data[key] for key in ("mergeStrip", "mergePins")})
        else:
            self._age()
            fields.update(self._feed.ledger_marks())

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
            "interactive": self._feed.interactive(),
            **fields,
            "now": now,
        }
