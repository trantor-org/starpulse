"""Feed writes: its pulls and the lanes a board write records."""

import contextlib
import threading
import time
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

from starpulse.board.model import lane_writes, write_steps
from starpulse.event_log import lane_events
from starpulse.event_log.wake import StopEvent
from starpulse.machine_engine.model.transitions import lane_id

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from sqlalchemy import Connection

    from starpulse.board.model.seam import Written
    from starpulse.event_log.event_log import EventLog
from starpulse.board.model.feed.shared import LaneRecorder, logger

#: A lane change as the history keeps it: `(task, at, from, to)`, `at` in epoch seconds.
LaneRow = tuple[str, float, str | None, str]


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

    def recording_of(self, task_id: str) -> threading.RLock:
        """The lock one task's write holds from the board's write to the record of its lane, so a write of the same task,
        the task actor's included, waits for it and a write of any other task does not. An alias shares its task's lock."""
        return self._recording_of.setdefault(self._keys.canonical(task_id) if self._keys else task_id, threading.RLock())

    def record_written(self, task_id: str, lane: str, at: float, who: tuple[str, str, str]) -> None:
        """Record the lane a board write put `task_id` in at `at`, naming `who` (actor, session, harness), in the history
        and with a log as its `lane_events` entry, in one transaction (`LaneRecorder`). The caller holds
        `recording_of(task_id)` from the write. A history that cannot be written is logged."""
        if self._lanes is None:
            return
        try:
            if self._lane_change(task_id, lane, at, who)(None):
                self._lane_log.committed()
        except Exception as exc:  # the history is down; the task is placed and its change recorded then
            logger.warning("StarPulse: cannot record the lane change of %s: %s", task_id, exc)

    @contextlib.contextmanager
    def recording_moves(self, who: tuple[str, str, str]) -> Iterator[None]:
        """Record each move a write inside appends to a Task's History in that append's transaction, naming `who`, so
        the move and its lane row land together: a process that ends before `record_written` still left the row."""
        if self._lanes is None:
            yield
            return
        logged: list[bool] = []

        def recorder(task_id: str, lane: str, at: float) -> Callable[[Connection], bool]:
            change = self._lane_change(task_id, lane, at, who)

            def record(connection: Connection) -> bool:
                logged.append(change(connection))
                return logged[-1]

            return record

        with lane_writes.recording(recorder):
            yield
        if any(logged):
            self._lane_log.committed()

    def _lane_change(
        self, task_id: str, lane: str, at: float, who: tuple[str, str, str]
    ) -> Callable[[Connection | None], bool]:
        """The record of `task_id`'s move to `lane` at `at` by `who`, run in a connection's transaction or its own; True
        when it logged a `lane_events` entry."""
        task_id, lane = self._keys.canonical(task_id) if self._keys else task_id, lane_id(lane)
        kind = "" if self._lane_log is None else str((self._read_model.task(task_id) or {}).get("type") or "")
        event = None if self._lane_log is None else lane_events.change(task_id, lane, at, *who, kind=kind)
        lanes = self._lanes

        def record(connection: Connection | None) -> bool:
            return bool(lanes.record_lane(f"{task_id}@{lane}@{at}", task_id, lane, at, event=event, connection=connection)) and event is not None

        return record

    def record_write(self, task: str | None, who: tuple[str, str, str], write: Callable[[], Written]) -> Written:
        """Run `write` of `task` (None: the task the write makes, named by its output) holding the task's `recording_of`,
        so the task actor's write of the same task waits for it and no other write does, and record the lane it put the
        task in with `record_written`: a write refused, or one that moves no lane, records nothing. A create holds no lock:
        its id is new, and the creator's own lock orders the ids."""
        with self.recording_of(task) if task else contextlib.nullcontext():
            write_steps.step("feed")
            with self.recording_moves(who):
                written = write()
            if written.ok and written.lane:
                at = written.at or time.time()
                self.record_written(task or written.output, written.lane, at, who)
                for moved, lane in written.moves:
                    self.record_written(moved, lane, at, who)
                write_steps.step("record")
        return written
