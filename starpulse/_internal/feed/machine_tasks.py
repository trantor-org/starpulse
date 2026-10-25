"""Each lifecycle machine's tasks, held in memory and kept current from `machine:events`.

The page used to rebuild every non-Board machine from Claude Code transcripts. Each declared
writer of a machine event now publishes it, keyed by the task or the run it moved (`machine_events`), so
the server reads the stream once and keeps each one's latest state per machine. A run is kept
only inside the feed's window, since a harness alone emits a run-keyed event per step. An entry
for a machine the page does not draw, or naming an event the machine lacks, is dropped.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping

from pydantic import ValidationError

from starpulse._internal.feed.board_feed import BoardFeed, entry_position
from starpulse.contracts.adapters import MachineEvent, TaskKeys
from starpulse.machine_engine.model.transitions import tables

#: How many of a task's latest steps travel with it, so a page that connected after several steps can still walk each one.
TRAIL = 12
#: A machine a third party moves (`source`) keeps more: its history is the data the task view totals, not a recent-steps strip,
#: and a worst-case pull request alone runs past 12 steps.
TRAIL_SOURCED = 120


class MachineTasks:
    """Places each task on the machine an entry names and hands the move to the feed.

    With `keys`, an entry whose task is not a key of that scheme is dropped; None places any key. A run is no task
    key, so `keys` leaves it be. `machines` are the machines the page draws, the feed's unless given.

    Entries arrive on the one consumer thread; the feed holds the page-facing state and its lock.
    """

    def __init__(
        self, feed: BoardFeed, keys: TaskKeys | None = None, machines: Mapping[str, dict] | None = None
    ) -> None:
        self._feed = feed
        self._keys = keys
        drawn = feed.machines if machines is None else machines
        self._tables = tables(drawn)
        self._trail = {name: TRAIL_SOURCED if machine.get("source") else TRAIL for name, machine in drawn.items()}
        #: Each placed run by its last move, oldest first, so the runs past the window go from the front.
        self._runs: dict[tuple[str, str], float] = {}
        self._expected: int | None = None
        self._seen = 0
        #: Set once the stream has been read up to the last entry it held when the server started.
        self.ready = threading.Event()

    def expect(self, last_id: str) -> None:
        """Mark the tasks ready once the entry `last_id` has been read; `0` is an empty stream."""
        self._expected = entry_position(last_id)
        self._check_ready()

    def await_stream(self) -> None:
        """Nothing to say before the stream is reached: an empty machine level is a correct one."""

    def _check_ready(self) -> None:
        """Turn ready once the entry expected has been read, and hand every connected page the tasks the replay placed in
        one snapshot, as the Board does: a move per replayed entry would send each page the stream's whole retention."""
        if self._expected is None or self._seen < self._expected or self.ready.is_set():
            return
        self.ready.set()
        self._feed.publish("snapshot", self._feed.snapshot())

    def put(self, event: MachineEvent, *, publish: bool = True) -> None:
        """Move one task or run by a machine event; one for a machine the page does not draw, a task key outside the
        scheme, or a run older than the window is dropped."""
        flow, run = event.machine, event.run
        task = event.task or run
        table = self._tables.get(flow)
        if task is None or table is None or run is None and self._keys is not None and not self._keys.matches(task):
            return
        window = self._feed.window_s
        if run is not None and window is not None and event.time < time.time() - window:
            return
        before = self._feed.machine_task(flow, task)
        state = table.target(before["state"] if before else None, event.event)
        if state is None:
            return
        trail = [*(before["trail"] if before else []), {"state": state, "event": event.event, "at": event.time}]
        self._feed.move(
            flow,
            {
                "id": task,
                "title": task,
                "model": "",
                "task": task,
                "state": state,
                "steps": (before["steps"] if before else 0) + 1,
                "trail": trail[-self._trail[flow] :],
                "active": event.time,
            },
            publish=publish,
        )
        if run is not None:
            self._keep_run(flow, run, event.time, window)

    def _keep_run(self, flow: str, run: str, at: float, window: float | None) -> None:
        """Note the run's latest move and forget each run whose last move has left the window, so a stream of runs
        holds the feed no further than the window reaches."""
        self._runs.pop((flow, run), None)
        self._runs[flow, run] = at
        if window is None:
            return
        since = time.time() - window
        while self._runs:
            oldest = next(iter(self._runs))
            if self._runs[oldest] >= since:
                break
            del self._runs[oldest]
            self._feed.forget(*oldest)

    def handle_entry(self, entry_id: str, fields: dict) -> None:
        """Take one stream entry; one that is not a machine event of the contract is dropped."""
        self._seen = max(self._seen, entry_position(entry_id))
        try:
            event = MachineEvent.model_validate(fields)
        except ValidationError:
            event = None
        if event is not None:
            self.put(event, publish=self._expected is None or self.ready.is_set())
        self._check_ready()
