"""Feed writes: placing a task's lane, its pulls, ratings and saved state."""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, Any

from starpulse.board import criteria
from starpulse.contracts.adapters import BoardTask
from starpulse.event_log import lane_events, rating_events
from starpulse.machine_engine.model.stays import LaneRow
from starpulse.machine_engine.model.transitions import lane_id

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog
from starpulse.board.feed.shared import (
    SAVE_INTERVAL,
    LaneRecorder,
    TaskIndex,
    cited_pulls,
    cooled,
    is_cold,
    logger,
    settled_entry,
    task_agent,
)


class RecordsMixin:
    def pulls(self) -> dict[str, list[dict]]:
        """Each task's pull request state as `set_pulls` last took it."""
        with self._lock:
            return dict(self._pulls)

    def pull_answers(self) -> dict:
        """What the pull request reader last handed `set_pulls`, as saved; empty when nothing was."""
        with self._lock:
            return dict(self._pull_answers)

    def keep_source(self, source: dict) -> None:
        """Keep `source`, what the board adapter needs beside the Board to resume it, to save with the Board it now
        holds: a native board's file fingerprints, noted after the scan that placed them."""
        with self._lock:
            self._kept = source

    def source(self) -> dict:
        """What the adapter last kept (`keep_source`), or what `resume` restored; empty when neither happened."""
        with self._lock:
            return self._kept

    def keep_saved(self, stop: threading.Event, interval: float = SAVE_INTERVAL) -> None:
        """Save every `interval` seconds, and once more when `stop` is set."""
        while not stop.wait(interval):
            self.save()
        self.save()

    def spawn(self, target: Callable[[threading.Event], None], name: str) -> None:
        """Run `target(stopped)` on a daemon thread that `stop` ends: `target` returns once `stopped` is set."""
        thread = threading.Thread(target=target, args=(self.stopped,), name=name, daemon=True)
        self._threads.append(thread)
        thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """End every thread `spawn` began, and wait up to `timeout` seconds for each, so the feed saves its last
        checkpoint before the log it saves to is closed."""
        self.stopped.set()
        for thread in self._threads:
            thread.join(timeout)

    def date_lanes(self, lane_path: Callable[[str], list[dict]]) -> None:
        """Date a lane the feed replays by the history's last change into it (`History.lane_path`), not by the replay."""
        self._lane_path = lane_path

    def record_ratings(self, log: EventLog) -> None:
        """Show the ratings `log` holds in each snapshot, and append the changes `rate` records to it."""
        self._ratings = rating_events.Ratings(log)

    def rate(self, fields: dict[str, Any]) -> dict[str, Any] | None:
        """Record a change of a task's rating (`rating_events.change`): the task's rating now with its change count,
        or None when the change is not recorded (no ratings log, or the append failed)."""
        return None if self._ratings is None else self._ratings.rate(fields)

    def record_take_over(self, task_id: str) -> None:
        """Show `task_id` as interactive in each snapshot from now on, and tell the streams it changed."""
        self._interactive.add(task_id)
        self._publish("task", {"id": task_id, "agent": self._open.get(task_id), "settled": None})

    def record_lanes(self, lanes: LaneRecorder, log: EventLog | None = None, *, live: bool = True) -> None:
        """Keep each lane change the feed applies in `lanes` (`HistoryStore.record_lane`), and with a `log`, append
        the change as a `lane_events` entry under the same event id once `lanes` has written it.

        The event id names the task, the lane and when it entered it, so a replay of a change the history holds
        repeats nothing. `put` records only a change no server write recorded already (`writes._record_written`), as
        `external`: a lane the history already holds is no change. A history that cannot be written is logged: the task
        is still placed. A feed that is not `live` records no lane as `put` places it: the feed that places the same
        task from a replica records it.
        """
        self._lanes = lanes
        self._lane_log = log
        self._live_lanes = live

    def index_tasks(self, search: TaskIndex) -> None:
        """Keep every task the feed places in `search`, and drop each one it retracts.

        A task is indexed as it arrives, before the feed decides whether anything it draws changed, so a change the
        page does not show (an acceptance criterion, a note) is still searchable. An index that cannot be written is
        logged: the task is still placed.
        """
        self._search = search

    def read_lanes(self, lane_rows: Callable[..., list[LaneRow]]) -> None:
        """Read the Ledger's lane moves through `lane_rows` (`LaneHistory.lane_rows`)."""
        self._lane_rows = lane_rows

    def put(self, task: BoardTask) -> None:
        """Place a task the board contract describes; one outside the adapter's key scheme is dropped."""
        if self._keys is not None and not self._keys.matches(task.id):
            return
        with self.recording:
            change = self._place(task)
            if self._search is not None:
                try:
                    self._search.index(task, self._done_at(task.id))  # placed first: the done lane's entry dates it
                except Exception as exc:  # the index is down; the task is placed and the next change is indexed
                    logger.warning("StarPulse: cannot index %s for search: %s", task.id, exc)
            if change is None:
                return
            if self._lanes is not None and self._live_lanes:
                lane, entered = change
                try:
                    if task.settled:
                        path = self._lane_path(task.id)
                        if path and lane_id(path[-1]["to"]) == lane:
                            return
                        # a file stamped in a zone behind the moves' would settle before them and open the trajectory
                        entered = max(entered, path[-1]["at"]) if path else entered
                    event_id = f"{task.id}@{lane}@{entered}"
                    event = None
                    if self._lane_log is not None:
                        # a lane the server's write recorded already is no change to the history, so this entry is dropped
                        event = lane_events.entry(
                            task.model_copy(update={"lane": lane}), entered, lane_events.EXTERNAL_ACTOR
                        )
                    if self._lanes.record_lane(event_id, task.id, lane, entered, event=event) and event is not None:
                        self._lane_log.committed()
                except Exception as exc:  # the history is down; the task is placed and the next change is recorded
                    logger.warning("StarPulse: cannot record the lane change of %s: %s", task.id, exc)
        if not self._replaying():
            self._refresh_ledgers()  # the Ledger reads the move from the history; the replay's moves are built once, at its end

    def record_written(self, task_id: str, lane: str, at: float, who: tuple[str, str, str]) -> None:
        """Record the lane a board write put `task_id` in at `at`, naming `who` (actor, session, harness), in the history
        and with a log as its `lane_events` entry, in one transaction (`LaneRecorder`). The caller holds `recording`
        from the write, so the placement of the change finds it recorded. A history that cannot be written is logged:
        the placement records the change as `external`. A feed that is not `live` records it all the same: its process
        made the write."""
        if self._lanes is None:
            return
        task_id, lane = self._keys.canonical(task_id) if self._keys else task_id, lane_id(lane)
        event = None if self._lane_log is None else lane_events.change(task_id, lane, at, *who)
        try:
            if self._lanes.record_lane(f"{task_id}@{lane}@{at}", task_id, lane, at, event=event) and event is not None:
                self._lane_log.committed()
        except Exception as exc:  # the history is down; the task is placed and its change recorded then
            logger.warning("StarPulse: cannot record the lane change of %s: %s", task_id, exc)

    def _place(self, task: BoardTask) -> tuple[str, float] | None:
        """Place `task`; the lane it entered and when, if that is a change of lane, else None.

        A task that left the lanes by archive enters `ARCHIVED`, and one swept on enters `COMPLETED` where the Board has
        it: its file keeps the status it had, and the Board draws the folder it sits in as the lane.
        """
        with self._lock:
            filed = self._settled.get(task.id)
            self._assignees[task.id] = task.profile
            self._cited[task.id] = cited_pulls(task)
            agent, settled = (None, settled_entry(task)) if task.settled else (task_agent(task), None)
            if agent:
                agent["runs"] = self._task_runs().get(task.id, [])
            before = self._open.get(task.id)
            if agent and before:
                # the lane the task left on its last move, kept while the hourly reconcile republishes it in place
                previous = before["state"] if before["state"] != agent["state"] else before.get("previous")
                if previous:
                    agent["previous"] = previous
            self._gated.discard(task.id)
            if agent and task.lane == self._roles.waiting and criteria.authored(task.description):
                self._gated.add(task.id)
            if agent:
                agent["entered"] = self._entered(task, before)
                agent["workable"], agent["workable_since"] = self._workable(agent)
                agent = self._expiring(cooled(agent, self._clock, self._roles.done))
            if before == agent and self._settled.get(task.id) == settled:
                return None  # an hourly reconcile republishes every task; only a change reaches the page
            settling = (
                settled is not None
                and settled["state"] in self._settle_lanes
                and (filed or {}).get("state") != settled["state"]
            )
            if agent is None:
                self._open.pop(task.id, None)
                if settled:
                    self._settled[task.id] = settled
            else:
                self._open[task.id] = agent
                self._settled.pop(task.id, None)
            self._link(task.id, (before or {}).get("dependencies", ()), (agent or {}).get("dependencies", ()))
            if agent is None or not is_cold(agent):  # a page keeps a task that cooled until it reloads
                self._publish("task", {"id": task.id, "agent": agent, "settled": settled})
            self._reassess(self._dependents.get(task.id, ()))
            if settling:
                return settled["state"], settled["at"] or self._clock()
            if agent and (before is None or before["state"] != agent["state"]):
                return task.lane, agent["entered"]
            return None

    def retract(self, task_id: str) -> None:
        """Remove a task the adapter's source no longer holds, open or settled; a task not placed is a no-op."""
        if self._search is not None:
            try:
                self._search.remove(task_id)
            except Exception as exc:  # the index is down; a stale hit is dropped when the task is next indexed
                logger.warning("StarPulse: cannot drop %s from the search index: %s", task_id, exc)
        with self._lock:
            self._assignees.pop(task_id, None)
            self._cited.pop(task_id, None)
            gone = self._open.pop(task_id, None)
            if gone is None and self._settled.pop(task_id, None) is None:
                return
            self._gated.discard(task_id)
            self._link(task_id, (gone or {}).get("dependencies", ()), ())
            self._publish("task", {"id": task_id, "agent": None, "settled": None})
            self._reassess(self._dependents.get(task_id, ()))

    def _entered(self, task: BoardTask, before: dict | None) -> float:
        """When `task` entered its lane: kept while it stays there, for a move read live the time the board gives (else
        now), else the history's date."""
        if before and before["state"] == task.lane and "entered" in before:
            return before["entered"]
        if not self.ready.is_set():
            try:
                path = self._lane_path(task.id)
            except Exception as exc:  # the history is down; the task is still placed, dated now
                logger.warning("StarPulse: cannot read the lane history of %s: %s", task.id, exc)
                path = []
            dated = [c["at"] for c in path if lane_id(c["to"]) == task.lane]
            if dated:
                return dated[-1]
        return self._clock() if task.observed_at is None else task.observed_at

    def _link(self, task_id: str, before: Collection[str], after: Collection[str]) -> None:
        """Keep each dependency's dependents current when `task_id` moves from depending on `before` to `after`."""
        for dependency in set(before) - set(after):
            self._dependents[dependency].discard(task_id)
        for dependency in set(after) - set(before):
            self._dependents.setdefault(dependency, set()).add(task_id)

    def _done_at(self, task_id: str) -> float | None:
        """When the task was done, or None when it is not: completed (0 when the board does not say when) or in the done lane."""
        if (settled := self._settled.get(task_id)) is not None:
            return (settled["at"] or 0.0) if settled["state"] == "completed" else None
        agent = self._open.get(task_id)
        return agent["entered"] if agent and agent["state"] == self._roles.done else None

    def _unblocked(self, agent: dict) -> bool:
        return all(self._done_at(dependency) is not None for dependency in agent["dependencies"])

    def _workable(self, agent: dict) -> tuple[bool, float | None]:
        """Whether the task can be worked, and since when; the caller holds the lock."""
        if not self._unblocked(agent) or (agent["id"] in self._gated and agent["id"] not in self._met):
            return False, None
        since = max(
            [agent["entered"], self._met.get(agent["id"], 0.0)]
            + [self._done_at(d) or 0.0 for d in agent["dependencies"]]
        )
        return True, since

    def _reassess(self, task_ids: Collection[str]) -> None:
        """Work out again whether each open task of `task_ids` is workable and publish those that changed."""
        for task_id in sorted(task_ids):
            if (agent := self._open.get(task_id)) is None or is_cold(agent):
                continue
            workable, since = self._workable(agent)
            if (agent["workable"], agent["workable_since"]) != (workable, since):
                agent = {**agent, "workable": workable, "workable_since": since}
                self._open[task_id] = agent
                self._publish("task", {"id": task_id, "agent": agent, "settled": None})
