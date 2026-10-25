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

Answers 201, 400 (the entry is wrong), 401 (no known token), 403 (a machine, actor or source the producer may not
use), 413 (`data` over the cap) or 503 (the log did not take an entry; every entry carries a stable id, so the sender
posts the batch again).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from starpulse._internal.config.config import MAX_BATCH
from starpulse._internal.runs import run_events
from starpulse._internal.runs.ingest import run_event, token_owner
from starpulse.event_log.events import STREAM

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse._internal.config.config import Producer
    from starpulse.event_log.event_log import EventLog

#: The structured and batch content types the route takes.
SINGLE = "application/cloudevents+json"
BATCH = "application/cloudevents-batch+json"
#: The largest `data` object accepted, as JSON text: a machine event carries a pointer, not a payload.
MAX_DATA = 8 * 1024


class _Refused(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status


def _text(event: Mapping[str, Any], key: str) -> str:
    value = event.get(key)
    if not (isinstance(value, str) and value):
        raise _Refused(400, f"{key} must be non-empty text")
    return value


def _optional_text(event: Mapping[str, Any], key: str) -> str | None:
    return None if event.get(key) is None else _text(event, key)


def _epoch(value: object, now: float) -> float:
    if value is None:
        return now
    try:
        stamped = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        stamped = None
    if stamped is None or stamped.tzinfo is None:
        raise _Refused(400, "time must be an RFC 3339 timestamp with an offset")
    return stamped.timestamp()


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
            if self._log._append(stream, fields, event_id=event_id) is None:
                return 503, {"error": "the event log did not take the event; send it again"}
        return 201, {"accepted": True}

    def _entry(self, producer: Producer, event: object) -> tuple[str, str, dict[str, Any]]:
        """The stream, event id and fields one CloudEvent appends, or `_Refused` with the reason."""
        if not isinstance(event, dict):
            raise _Refused(400, "an event is a JSON object")
        if event.get("specversion") != "1.0":
            raise _Refused(400, 'specversion must be "1.0"')
        event_id, source = _text(event, "id"), _text(event, "source")
        if source != producer.name:
            raise _Refused(403, f"source must be the producer's own name, {producer.name}")
        if event.get("machine") is None and event.get("type") in run_events.EVENTS:
            return run_events.STREAM, f"{producer.name}/{event_id}", self._run_entry(producer, event)
        fields = self._machine_entry(producer, event, event_id)
        return STREAM, fields["event_id"], fields

    def _run_entry(self, producer: Producer, event: dict[str, Any]) -> dict[str, Any]:
        """The `runs:events` fields of a Step event; the producer is the run's `instance` unless it is `local`."""
        data = event.get("data")
        if not isinstance(data, dict):
            raise _Refused(400, "a run event carries data: workflow, status and, for a step, step and depends")
        if len(json.dumps(data)) > MAX_DATA:
            raise _Refused(413, f"data is at most {MAX_DATA} bytes")
        wanted = {**data, "event": event["type"], "run_id": event.get("subject")}
        if isinstance(fault := run_event(wanted), str):
            raise _Refused(400, fault)
        return run_events.entry(
            event["type"],
            data["workflow"],
            event["subject"],
            data["status"],
            now=_epoch(event.get("time"), self._clock()),
            step=data.get("step"),
            depends=data.get("depends"),
            instance=producer.name,
        )

    def _machine_entry(self, producer: Producer, event: dict[str, Any], event_id: str) -> dict[str, Any]:
        """The `machine:events` fields of one machine CloudEvent."""
        name, machine, actor = (_text(event, k) for k in ("type", "machine", "actor"))
        if machine not in producer.machines:
            raise _Refused(403, f"producer {producer.name} may not write machine {machine}")
        if actor not in producer.actors:
            raise _Refused(403, f"producer {producer.name} may not write as {actor}")
        self._declared(machine, name, actor)
        task, run = _optional_text(event, "subject"), _optional_text(event, "run")
        if (task is None) == (run is None):
            raise _Refused(400, "key an event by exactly one of subject (a task) and run")
        data = event.get("data")
        if data is not None and not isinstance(data, dict):
            raise _Refused(400, "data must be a JSON object")
        if data is not None and len(json.dumps(data)) > MAX_DATA:
            raise _Refused(413, f"data is at most {MAX_DATA} bytes")
        return {
            "event_id": f"{producer.name}/{event_id}",
            "machine": machine,
            "event": name,
            **({"task": task} if task is not None else {"run": run}),
            "actor": actor,
            "time": _epoch(event.get("time"), self._clock()),
            "source": producer.name,
            **({"data": data} if data is not None else {}),
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
