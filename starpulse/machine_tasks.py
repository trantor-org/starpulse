"""Each lifecycle machine's tasks, held in memory and kept current from `machine:events`.

The page used to rebuild every non-Board machine from Claude Code transcripts. Each declared
writer of a machine event now publishes it, keyed by the task it moved (`machine_events`), so
the server reads the stream once and keeps each task's latest state per machine. An entry
keyed by a run, for a machine the page does not draw, or naming an event the machine lacks, is
dropped.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Mapping

from pydantic import ValidationError

from starpulse import events as machine_events
from starpulse.board_feed import BoardFeed, stream_id
from starpulse.contracts import MachineEvent, TaskKeys
from starpulse.streams import StreamConsumer

#: How many of a task's latest steps travel with it, so a page that connected after several steps can still walk each one.
TRAIL = 12


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
        self._tables = tables(feed.machines if machines is None else machines)
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
                "trail": trail[-TRAIL:],
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


def build_consumer(tasks: MachineTasks, group: str) -> StreamConsumer:
    """The `machine:events` reader for `tasks`, in its own group so each running view sees every entry."""
    return StreamConsumer.from_env(
        machine_events.REDIS_ENV_PREFIX,
        stream=machine_events.STREAM,
        group=group,
        consumer=group,
        handler=tasks.handle_entry,
    )
