"""Each lifecycle machine's tasks, held in memory and kept current from `machine:events`.

The page used to rebuild every non-Board machine from Claude Code transcripts. Each declared
writer of a machine event now publishes it, keyed by the task it moved (`machine_events`), so
the server reads the stream once and keeps each task's latest state per machine. An entry
keyed by a run, for a machine the page does not draw, or naming an event the machine lacks, is
dropped.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from pydantic import ValidationError

from starpulse.contracts.adapters import MachineEvent, TaskKeys
from starpulse.domain.transitions import tables
from starpulse.projections.board_feed import BoardFeed, stream_id

#: How many of a task's latest steps travel with it, so a page that connected after several steps can still walk each one.
TRAIL = 12
#: A machine a third party moves (`source`) keeps more: its history is the data the task view totals, not a recent-steps strip,
#: and a worst-case pull request alone runs past 12 steps.
TRAIL_SOURCED = 120


class MachineTasks:
    """Places each task on the machine an entry names and hands the move to the feed.

    With `keys`, an entry whose task is not a key of that scheme is dropped; None places any key. `machines` are
    the machines the page draws, the feed's unless given.

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
        self._expected: tuple[int, int] | None = None
        self._seen = (0, 0)
        #: Set once the stream has been read up to the last entry it held when the server started.
        self.ready = threading.Event()

    def expect(self, last_id: str) -> None:
        """Mark the tasks ready once the entry `last_id` has been read; `0-0` is an empty stream."""
        self._expected = stream_id(last_id)
        self._check_ready()

    def await_stream(self) -> None:
        """Nothing to say before the stream is reached: an empty machine level is a correct one."""

    def _check_ready(self) -> None:
        if self._expected is not None and self._seen >= self._expected:
            self.ready.set()

    def put(self, event: MachineEvent) -> None:
        """Move one task by a machine event; one that names a run, a machine the page does not draw, or a key outside the scheme is dropped."""
        flow, task = event.machine, event.task
        table = self._tables.get(flow)
        if task is None or table is None or self._keys is not None and not self._keys.matches(task):
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
        )

    def handle_entry(self, entry_id: str, fields: dict) -> None:
        """Take one stream entry; one that is not a machine event of the contract is dropped."""
        self._seen = max(self._seen, stream_id(entry_id))
        self._check_ready()
        try:
            event = MachineEvent.model_validate(fields)
        except ValidationError:
            return
        self.put(event)
