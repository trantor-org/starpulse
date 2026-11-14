"""A run is an observed event stream: one stream per run in the event store, appended to by every entry path.

The CloudEvents ingest (HTTP and gRPC) and every run adapter write `runs:events` entries; `record_run_streams` copies each
into the stream of its run (subject kind `run`, subject id `<workflow>/<run id>`), so the stream is the same however a
run was seen. A run event the stream already holds (the entry's event id is its `causation_id`) adds nothing; a
correction, read again from the source, has an id of its own and appends after the Event it corrects, which stays.
"""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy.exc import OperationalError

from starpulse.event_log.event_log import Entry, EventLog
from starpulse.event_log.wake import StopEvent
from starpulse.event_log.store import EventStore, NewEvent, StaleVersion, StoredEvent
from starpulse.runs.model import run_events

SUBJECT = "run"
#: The writer of an entry no producer posted: a run adapter's.
ADAPTER = "adapter"
#: The checkpoint name of the position `record_run_streams` has reached in `runs:events`.
CHECKPOINT = "run-streams"


class RunStreams:
    """The run streams of an event store."""

    def __init__(self, store: EventStore) -> None:
        self._store = store

    def read(self, workflow: str, run_id: str) -> list[StoredEvent]:
        """The run's Events in the order they were observed."""
        return self._store.read(SUBJECT, f"{workflow}/{run_id}")

    def unfinished(self, workflow: str, run_id: str) -> list[str]:
        """The steps the run's stream shows started and never finished, the gap a lost Event leaves."""
        open_steps: dict[str, None] = {}
        for event in self.read(workflow, run_id):
            step = event.payload.get("step")
            if step is None:
                continue
            if event.type == "StepStarted":
                open_steps[step] = None
            else:
                open_steps.pop(step, None)
        return list(open_steps)

    def record(self, event_id: str, fields: dict[str, Any]) -> bool:
        """Append the entry as an Event of its run's stream, unless the stream holds it already.

        An entry with no `event` field predates the field (phase-only rows, before the schema change): it is no Event, so it is skipped.
        """
        if "event" not in fields:
            return False
        subject = f"{fields['workflow']}/{fields['run_id']}"
        writer = fields.get("instance") or ADAPTER
        event = NewEvent(
            type=fields["event"],
            payload={key: value for key, value in fields.items() if key not in ("event", "instance", "time")},
            actor=writer,
            writer=writer,
            causation_id=event_id,
        )
        while True:
            seen = self._store.read(SUBJECT, subject)
            if any(known.causation_id == event_id for known in seen):
                return False
            try:
                self._store.append(SUBJECT, subject, len(seen), [event], at=float(fields["time"]))
            except StaleVersion:
                continue  # another entry reached the stream first: read it again
            return True


def record_run_streams(streams: RunStreams, log: EventLog, stop: StopEvent) -> None:
    """Copy the log's run entries into `streams` until `stop`, from the entry after the last one recorded (the oldest retained when none).

    The position is kept after every entry, so a restart does not read each retained entry's stream again. An entry
    read twice (a transient failure, a crash between the append and the save) repeats nothing: `RunStreams.record` skips
    an entry the stream holds. A database that cannot be reached is the sink down, not the entry bad, so the entry is
    read again on the next poll.
    """
    checkpoints = log.checkpoints
    position, _ = checkpoints.load(CHECKPOINT)
    tail = log.tail(run_events.STREAM, after=position)

    def record(entry: Entry) -> None:
        streams.record(entry.event_id, entry.fields)
        checkpoints.save(CHECKPOINT, entry.id)

    tail.run(record, stop, transient=(OperationalError,))
