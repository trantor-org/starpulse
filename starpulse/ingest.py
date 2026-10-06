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
from starpulse.config import RunsInstance
from starpulse.contracts import RunStatus
from starpulse.event_log import EventLog

#: The largest event body accepted: a run event is a few hundred bytes, so this only stops a sender filling memory.
MAX_BODY = 64 * 1024


def tokens(instances: Iterable[RunsInstance], environ: Mapping[str, str]) -> dict[str, str]:
    """Each instance's ingest token, by instance name, from the variable its `token_env` names.

    Raises `ValueError` for a named variable that is unset or empty, and for two instances holding one token, since a
    token must say which instance it speaks for."""
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


def _decoded(raw: bytes) -> dict[str, Any] | str:
    """The event's fields the contract allows, or the reason it is refused."""
    try:
        event = json.loads(raw)
    except ValueError:
        return "the body is not JSON"
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

    def _instance(self, authorization: str | None) -> str | None:
        """The instance the bearer token belongs to; every token is compared, so the time taken names none of them."""
        scheme, _, presented = (authorization or "").partition(" ")
        owner = None
        for name, token in self._tokens.items():
            if hmac.compare_digest(token.encode(), presented.encode()) and scheme.lower() == "bearer" and presented:
                owner = name
        return owner

    def __call__(self, authorization: str | None, raw: bytes) -> tuple[int, dict[str, Any]]:
        if (instance := self._instance(authorization)) is None:
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
