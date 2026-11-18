"""Feed writes: its pulls, ratings and the lanes a board write records."""

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from starpulse.board.model import write_steps
from starpulse.event_log import lane_events, rating_events
from starpulse.event_log.wake import StopEvent
from starpulse.machine_engine.model.stays import LaneRow
from starpulse.machine_engine.model.transitions import lane_id

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.board.model.seam import Written
    from starpulse.event_log.event_log import EventLog
from starpulse.board.model.feed.shared import LaneRecorder, logger


class RecordsMixin:
    def pulls(self) -> dict[str, list[dict]]:
        """Each task's pull request state as `set_pulls` last took it."""
        with self._lock:
            return dict(self._pulls)

    def pull_answers(self) -> dict:
        """What the pull request reader last handed `set_pulls`, as saved; empty when nothing was."""
        with self._lock:
            return dict(self._pull_answers)

    def spawn(self, target: Callable[[StopEvent], None], name: str) -> None:
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

    def record_ratings(self, log: EventLog) -> None:
        """Show the ratings `log` holds in each snapshot, and append the changes `rate` records to it."""
        self._ratings = rating_events.Ratings(log)

    def ratings(self) -> dict[str, dict]:
        """Each rated task's latest rating; none when the feed records none."""
        return {} if self._ratings is None else self._ratings.latest()

    def rate(self, fields: dict[str, Any]) -> dict[str, Any] | None:
        """Record a change of a task's rating (`rating_events.change`): the task's rating now with its change count,
        or None when the change is not recorded (no ratings log, or the append failed)."""
        return None if self._ratings is None else self._ratings.rate(fields)

    def record_take_over(self, task_id: str) -> None:
        """Show `task_id` as interactive in each snapshot from now on, and tell the streams it changed."""
        self._interactive.add(task_id)
        self._publish("task", {"id": task_id, "agent": self.drawn_task(task_id)[0], "settled": None})

    def record_lanes(self, lanes: LaneRecorder, log: EventLog | None = None) -> None:
        """Keep each lane a board write puts a task in (`record_written`) in `lanes` (`HistoryStore.record_lane`), and
        with a `log`, append the change as a `lane_events` entry under the same event id once `lanes` has written it.
        The event id names the task, the lane and when it entered it, so a replay of a change the history holds
        repeats nothing."""
        self._lanes = lanes
        self._lane_log = log

    def read_lanes(self, lane_rows: Callable[..., list[LaneRow]]) -> None:
        """Read the Ledger's lane moves through `lane_rows` (`HistoryStore.lane_rows`)."""
        self._lane_rows = lane_rows

    def alias(self, alias: str, task: str) -> None:
        """Answer `alias` with the task `task`: the read model holds no aliases."""
        self._aliases[alias] = task

    def record_written(self, task_id: str, lane: str, at: float, who: tuple[str, str, str]) -> None:
        """Record the lane a board write put `task_id` in at `at`, naming `who` (actor, session, harness), in the history
        and with a log as its `lane_events` entry, in one transaction (`LaneRecorder`). The caller holds `recording`
        from the write. A history that cannot be written is logged."""
        if self._lanes is None:
            return
        task_id, lane = self._keys.canonical(task_id) if self._keys else task_id, lane_id(lane)
        event = None if self._lane_log is None else lane_events.change(task_id, lane, at, *who)
        try:
            if self._lanes.record_lane(f"{task_id}@{lane}@{at}", task_id, lane, at, event=event) and event is not None:
                self._lane_log.committed()
        except Exception as exc:  # the history is down; the task is placed and its change recorded then
            logger.warning("StarPulse: cannot record the lane change of %s: %s", task_id, exc)

    def record_write(self, task: str | None, who: tuple[str, str, str], write: Callable[[], Written]) -> Written:
        """Run `write` of `task` (None: the task the write makes, named by its output) holding `recording`, and record
        the lane it put the task in with `record_written`: a write refused, or one that moves no lane, records nothing."""
        with self.recording:
            write_steps.step("feed")
            written = write()
            if written.ok and written.lane:
                self.record_written(task or written.output, written.lane, written.at or time.time(), who)
                write_steps.step("record")
        return written
