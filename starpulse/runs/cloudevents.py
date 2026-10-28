"""The CloudEvents ingest: `POST /api/machine-events`, the one public write path for a machine event.

A producer posts one CloudEvents 1.0 structured JSON event (`application/cloudevents+json`) or a JSON array of them
(`application/cloudevents-batch+json`) with `Authorization: Bearer <token>`:

    {"specversion": "1.0", "id": "e1", "source": "ci-bot", "type": "WORKTREE_READY", "subject": "PROJ-1",
     "time": "2026-10-18T22:00:00Z", "machine": "in-progress", "actor": "ci", "data": {"sha": "abc"}}

`id` is the event id, `source` the producer (its `[[producers]]` name), `type` the machine's event, `subject` the task
it moved, or the extension `run` the run it moved: exactly one of the two. `machine` and `actor` are extensions;
`time` and `data` (a JSON object under `MAX_DATA`) are optional. Each token belongs to one producer, which writes only
its own machines and actors. A batch is checked whole before any entry is appended, so a refused entry writes none.

A run's Step event rides the same route: `type` is `StepStarted` or `StepFinished`, there is no `machine`, `subject`
is the run id and `data` carries `workflow`, `status` and, for a step's entry, `step` and `depends`. It lands on the
runs stream under the producer's name as its `instance`, and a producer needs no machines to post it.

A qa lens's verdict does too: `type` is `VerdictRecorded`, there is no `machine`, `subject` is the task and `data`
carries `lens`, `round`, `outcome` (`PASS` or `CHANGES`) and an optional `reason`. A verdict missing any of the three,
or one with another outcome, is refused. It lands on the `task:verdicts` stream with the producer as its `source`.

Answers 201, 400 (the entry is wrong), 401 (no known token), 403 (a machine, actor or source the producer may not
use), 413 (`data` over the cap) or 503 (the log did not take an entry; every entry carries a stable id, so the sender
posts the batch again).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from importlib import import_module
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from starpulse.board.model.adapter_types import module_name
from starpulse.contracts.adapters import CloudEvent, VerdictEvent
from starpulse.runs.config import MAX_BATCH
from starpulse.runs import run_events
from starpulse.runs.ingest import run_event, token_owner
from starpulse.event_log import verdict_events
from starpulse.event_log.events import STREAM

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog
    from starpulse.runs.config import Producer

#: The structured and batch content types the route takes.
SINGLE = "application/cloudevents+json"
BATCH = "application/cloudevents-batch+json"
#: The largest `data` object accepted, as JSON text: a machine event carries a pointer, not a payload.
MAX_DATA = 8 * 1024


class _Refused(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status


def _reason(invalid: ValidationError) -> str:
    """Each field a model refused, as `field: why`."""
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in invalid.errors())


class CloudEventsIngest:
    """Answers one `POST /api/machine-events`: `(authorization, content type, body)` to `(status, JSON body)`.

    `machines` are the machines the page draws (the feed's); `tokens` hold each producer's token by producer name."""

    def __init__(
        self,
        producers: Mapping[str, Producer],
        tokens: Mapping[str, str],
        log: EventLog,
        machines: Mapping[str, dict],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._producers, self._tokens, self._log, self._machines, self._clock = (
            producers,
            dict(tokens),
            log,
            machines,
            clock,
        )

    def owner(self, authorization: str | None) -> str | None:
        """The producer the bearer token belongs to, or None."""
        return token_owner(self._tokens, authorization)

    def __call__(self, authorization: str | None, content_type: str | None, raw: bytes) -> tuple[int, dict[str, Any]]:
        if (name := self.owner(authorization)) is None:
            return 401, {"error": "a valid producer token is required: Authorization: Bearer <token>"}
        media = (content_type or "").partition(";")[0].strip().lower()
        if media not in (SINGLE, BATCH):
            return 400, {"error": f"Content-Type must be {SINGLE} or {BATCH}"}
        try:
            body = json.loads(raw)
        except ValueError:
            return 400, {"error": "the body is not JSON"}
        sent = body if media == BATCH else [body]
        if not (isinstance(sent, list) and 0 < len(sent) <= MAX_BATCH):
            return 400, {"error": f"a batch is a JSON array of 1 to {MAX_BATCH} events"}
        return self.write(name, sent)

    def write(self, name: str, sent: list[Any]) -> tuple[int, dict[str, Any]]:
        """Check every event of `sent` as producer `name`, then append them all, or refuse and append none."""
        try:
            entries = [self._entry(self._producers[name], event) for event in sent]
        except _Refused as refused:
            return refused.status, {"error": str(refused)}
        for stream, event_id, fields in entries:
            if self._log.publish(stream, fields, event_id=event_id) is None:
                return 503, {"error": "the event log did not take the event; send it again"}
        return 201, {"accepted": True}

    def _entry(self, producer: Producer, event: object) -> tuple[str, str, dict[str, Any]]:
        """The stream, event id and fields one CloudEvent appends, or `_Refused` with the reason."""
        if not isinstance(event, dict):
            raise _Refused(400, "an event is a JSON object")
        try:
            parsed = CloudEvent.model_validate(event)
        except ValidationError as invalid:
            raise _Refused(400, _reason(invalid)) from None
        if parsed.source != producer.name:
            raise _Refused(403, f"source must be the producer's own name, {producer.name}")
        if parsed.data is not None and len(json.dumps(parsed.data)) > MAX_DATA:
            raise _Refused(413, f"data is at most {MAX_DATA} bytes")
        if parsed.machine is None and parsed.type in run_events.EVENTS:
            return run_events.STREAM, f"{producer.name}/{parsed.id}", self._run_entry(producer, parsed)
        if parsed.machine is None and parsed.type == verdict_events.EVENT:
            return verdict_events.STREAM, f"{producer.name}/{parsed.id}", self._verdict_entry(producer, parsed)
        fields = self._machine_entry(producer, parsed)
        return STREAM, fields["event_id"], fields

    def _at(self, event: CloudEvent) -> float:
        return self._clock() if event.time is None else event.time.timestamp()

    def _run_entry(self, producer: Producer, event: CloudEvent) -> dict[str, Any]:
        """The `runs:events` fields of a Step event; the producer is the run's `instance` unless it is `local`."""
        data = event.data
        if data is None or event.subject is None:
            raise _Refused(
                400, "a run event carries a subject and data: workflow, status and, for a step, step and depends"
            )
        if producer.adapter is not None and isinstance(data.get("status"), str):
            try:
                data = {**data, "status": import_module(module_name(producer.adapter)).status_of(data["status"])}
            except ValueError as unmapped:
                raise _Refused(400, str(unmapped)) from None
        if isinstance(fault := run_event({**data, "event": event.type, "run_id": event.subject}), str):
            raise _Refused(400, fault)
        return run_events.entry(
            event.type,
            data["workflow"],
            event.subject,
            data["status"],
            now=self._at(event),
            step=data.get("step"),
            depends=data.get("depends"),
            instance=producer.name,
        )

    def _verdict_entry(self, producer: Producer, event: CloudEvent) -> dict[str, Any]:
        """The `task:verdicts` fields of a verdict: a lens's `outcome` for the task in `round`."""
        data = event.data
        if data is None or event.subject is None:
            raise _Refused(400, "a verdict carries a subject (the task) and data: lens, round, outcome and reason")
        fields = verdict_events.entry(
            event.subject,
            data.get("lens"),
            data.get("round"),
            data.get("outcome"),
            data.get("reason", ""),
            self._at(event),
            producer.name,
        )
        try:
            VerdictEvent.model_validate(fields)
        except ValidationError as invalid:
            raise _Refused(400, _reason(invalid)) from None
        return fields

    def _machine_entry(self, producer: Producer, event: CloudEvent) -> dict[str, Any]:
        """The `machine:events` fields of one machine CloudEvent."""
        if event.machine is None or event.actor is None:
            raise _Refused(400, "a machine event names its machine and actor")
        if event.machine not in producer.machines:
            raise _Refused(403, f"producer {producer.name} may not write machine {event.machine}")
        if event.actor not in producer.actors:
            raise _Refused(403, f"producer {producer.name} may not write as {event.actor}")
        self._declared(event.machine, event.type, event.actor)
        if (event.subject is None) == (event.run is None):
            raise _Refused(400, "key an event by exactly one of subject (a task) and run")
        return {
            "event_id": f"{producer.name}/{event.id}",
            "machine": event.machine,
            "event": event.type,
            **({"task": event.subject} if event.subject is not None else {"run": event.run}),
            "actor": event.actor,
            "time": self._at(event),
            "source": producer.name,
            **({"data": event.data} if event.data is not None else {}),
        }

    def _declared(self, machine: str, name: str, actor: str) -> None:
        """Refuse an event the machine does not declare and an actor outside its writers; none declared allows any."""
        drawn = self._machines.get(machine)
        if drawn is None or machine == "board":
            raise _Refused(400, f"machine {machine} is not one this server draws events for")
        if name not in {t["event"] for t in drawn["transitions"]}:
            raise _Refused(400, f"machine {machine} declares no event {name}")
        writers = [w["actor"] for w in drawn.get("writers", {}).get(name, [])]
        if writers and actor not in writers:
            raise _Refused(400, f"{actor} is not a writer of {machine} {name}; its writers are {', '.join(writers)}")
