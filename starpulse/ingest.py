"""The HTTP runs ingest: `POST /api/runs/events`, the push path for a producer that cannot reach the event log.

A webhook-only engine (Cronicle, Rundeck, a GitHub `workflow_run` relay) posts one contract event as JSON, the fields
`starpulse emit` takes:

    {"phase": "start", "workflow": "<instance>/<workflow>", "run_id": "r1", "status": "running",
     "time": 1700000000.0, "step": "load", "depends": ["fetch"]}     # time, step and depends are optional

with `Authorization: Bearer <token>`. Each `[[runs]]` instance that names a `token_env` has its own token, read from
that environment variable at start, and a token pushes only workflows of its own instance: the `<instance>/` prefix
of `workflow` must be the instance the token belongs to. The entry appended to the event log carries the plain
workflow and an `instance` field (`run_events`), so no other instance's reader moves on it.

The answers: 201 when the log took the entry; 401 for a missing or wrong token; 403 for another instance's workflow;
400 for an event the contract does not allow; 503 when the log refused it; every refusal writes nothing.
"""

from __future__ import annotations

import hmac
import json
import math
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any, get_args

from starpulse import run_events
from starpulse.config import MAX_BATCH, RunsInstance, Source
from starpulse.contracts import RunStatus
from starpulse.event_log import EventLog
from starpulse.forward import FIELDS, PERSON, project

#: The largest event body accepted: a run event is a few hundred bytes, so this only stops a sender filling memory.
MAX_BODY = 64 * 1024
#: The largest forwarded batch accepted: `MAX_BATCH` events of a few hundred bytes each, with room for long keys.
MAX_FORWARD_BODY = 1024 * 1024


def tokens(instances: Iterable[RunsInstance | Source], environ: Mapping[str, str]) -> dict[str, str]:
    """Each instance's ingest token, by instance name, from the variable its `token_env` names.

    Raises `ValueError` for a named variable that is unset or empty, and for two instances holding one token, since a
    token must say which instance it speaks for. A forwarding `Source` is an instance here too."""
    found: dict[str, str] = {}
    for instance in instances:
        if not instance.token_env:
            continue
        if not (token := environ.get(instance.token_env)):
            raise ValueError(f"runs instance {instance.name}: {instance.token_env} is not set")
        if twin := next((name for name, other in found.items() if hmac.compare_digest(other, token)), None):
            raise ValueError(f"runs instances {twin} and {instance.name} hold the same token; each needs its own")
        found[instance.name] = token
    return found


def _owner(tokens: Mapping[str, str], authorization: str | None) -> str | None:
    """The instance the bearer token belongs to; every token is compared, so the time taken names none of them."""
    scheme, _, presented = (authorization or "").partition(" ")
    owner = None
    for name, token in tokens.items():
        if hmac.compare_digest(token.encode(), presented.encode()) and scheme.lower() == "bearer" and presented:
            owner = name
    return owner


def _decoded(raw: bytes) -> dict[str, Any] | str:
    """The event's fields the contract allows, or the reason it is refused."""
    try:
        event = json.loads(raw)
    except ValueError:
        return "the body is not JSON"
    return _run_event(event)


def _run_event(event: object) -> dict[str, Any] | str:
    """`event` when it is a run event the contract allows, else the reason it is refused."""
    if not isinstance(event, dict):
        return "the body must be a JSON object"
    for key in ("workflow", "run_id"):
        if not (isinstance(event.get(key), str) and event[key]):
            return f"{key} must be non-empty text"
    if event.get("phase") not in run_events.PHASES:
        return f"phase must be one of {', '.join(run_events.PHASES)}"
    if event.get("status") not in get_args(RunStatus):
        return f"status must be one of {', '.join(get_args(RunStatus))}"
    if "time" in event and not _epoch(event["time"]):
        return "time must be epoch seconds"
    step, depends = event.get("step"), event.get("depends")
    if step is not None and not (isinstance(step, str) and step):
        return "step must be non-empty text"
    if depends is not None and not (
        step is not None and isinstance(depends, list) and all(isinstance(name, str) for name in depends)
    ):
        return "depends must be a list of step names and needs step"
    return event


def _epoch(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


class Ingest:
    """Answers one `POST /api/runs/events`: `(authorization header, body)` to `(status, JSON body)`."""

    def __init__(self, tokens: Mapping[str, str], log: EventLog, clock: Callable[[], float] = time.time) -> None:
        self._tokens = dict(tokens)
        self._log = log
        self._clock = clock

    def __call__(self, authorization: str | None, raw: bytes) -> tuple[int, dict[str, Any]]:
        if (instance := _owner(self._tokens, authorization)) is None:
            return 401, {"error": "a valid instance token is required: Authorization: Bearer <token>"}
        if isinstance(event := _decoded(raw), str):
            return 400, {"error": event}
        owner, _, workflow = event["workflow"].partition("/")
        if not workflow:
            return 400, {"error": "workflow must be <instance>/<workflow>"}
        if owner != instance:
            return 403, {"error": f"this token may push only {instance}/<workflow>, not {event['workflow']}"}
        entry = run_events.entry(
            event["phase"],
            workflow,
            event["run_id"],
            event["status"],
            now=float(event["time"]) if "time" in event else self._clock(),
            step=event.get("step"),
            depends=event.get("depends"),
            instance=instance,
        )
        if self._log.append(run_events.STREAM, entry) is None:
            return 503, {"error": "the event log refused the entry; retry"}
        return 201, {"accepted": True}



def _machine_event(fields: dict[str, Any]) -> str | None:
    """The reason `fields` is not a machine event the contract allows, or None."""
    for key in ("machine", "event"):
        if not (isinstance(fields.get(key), str) and fields[key]):
            return f"{key} must be non-empty text"
    keyed = [key for key in ("task", "run") if key in fields]
    if len(keyed) != 1 or not (isinstance(fields[keyed[0]], str) and fields[keyed[0]]):
        return "an event is keyed by exactly one of task or run, as non-empty text"
    if not _epoch(fields.get("time")):
        return "time must be epoch seconds"
    if any(key in fields and not isinstance(fields[key], str) for key in PERSON):
        return "actor and assignee must be text"
    return None


class ForwardIngest:
    """Answers one `POST /api/forward`: `(authorization header, body)` to `(status, JSON body)`.

    The body is `{"opt_in": bool, "events": [{"event_id", "stream", "fields"}, ...]}`, at most `MAX_BATCH` events,
    sent by an instance's forwarder under that instance's token (a `[[sources]]` entry). Each event is cut to the
    fields its stream allows, and a person's name is kept only from a batch that opted in. It is appended to the
    log as `<source>/<event_id>`, so one source's ids never meet another's, and an event the log holds is not
    appended again: a batch sent twice adds nothing.

    The answers: 200 with the counts accepted and rejected (an invalid event is rejected and counted, so one cannot
    hold a forwarder's cursor); 401 for a missing or wrong token; 403 for an opt-in sent to a hub that takes
    aggregates only; 400 for a body that is not a batch; 503 when the log refused an event, which a resend repeats.
    A refusal writes nothing, bar the events of a 503 batch ahead of the refused one.
    """

    def __init__(self, tokens: Mapping[str, str], log: EventLog, *, aggregates_only: bool = False) -> None:
        self._tokens = dict(tokens)
        self._log = log
        self._aggregates_only = aggregates_only

    def __call__(self, authorization: str | None, raw: bytes) -> tuple[int, dict[str, Any]]:
        if (source := _owner(self._tokens, authorization)) is None:
            return 401, {"error": "a valid source token is required: Authorization: Bearer <token>"}
        try:
            body = json.loads(raw)
        except ValueError:
            return 400, {"error": "the body is not JSON"}
        sent = body.get("events") if isinstance(body, dict) else None
        opt_in = body.get("opt_in") if isinstance(body, dict) else None
        if not (isinstance(sent, list) and isinstance(opt_in, bool)):
            return 400, {"error": 'the body must be {"opt_in": true|false, "events": [...]}'}
        if len(sent) > MAX_BATCH:
            return 400, {"error": f"a batch is at most {MAX_BATCH} events"}
        if opt_in and self._aggregates_only:
            return 403, {"error": "this hub takes aggregates only; send the batch with opt_in false"}
        accepted = 0
        for item in sent:
            if (entry := _forwarded(source, opt_in, item)) is None:
                continue
            stream, event_id, fields = entry
            if self._log.append(stream, fields, event_id=event_id) is None:
                return 503, {"error": "the event log refused an entry; retry"}
            accepted += 1
        return 200, {"accepted": accepted, "rejected": len(sent) - accepted}


def _forwarded(source: str, opt_in: bool, item: object) -> tuple[str, str, dict[str, Any]] | None:
    """`(stream, event_id, fields)` as the hub stores one forwarded event from `source`, or None when it is invalid."""
    if not isinstance(item, dict):
        return None
    event_id, stream, fields = item.get("event_id"), item.get("stream"), item.get("fields")
    if not (isinstance(event_id, str) and event_id and stream in FIELDS and isinstance(fields, dict)):
        return None
    kept = project(stream, fields, opt_in=opt_in)
    if stream == run_events.STREAM:
        if isinstance(_run_event(kept), str):
            return None
        kept["instance"] = source
    elif _machine_event(kept) is not None:
        return None
    return stream, f"{source}/{event_id}", {**kept, "source": source}
