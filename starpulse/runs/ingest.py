"""The token and run-event helpers every push route shares."""

from __future__ import annotations

import hmac
import math
from collections.abc import Iterable, Mapping
from typing import Any, get_args

from starpulse._internal.config.config import Producer
from starpulse._internal.runs import run_events
from starpulse.contracts.adapters import RunStatus

#: The largest event body accepted: a run event is a few hundred bytes, so this only stops a sender filling memory.
MAX_BODY = 64 * 1024
#: The largest CloudEvents batch accepted: `MAX_BATCH` events of a few hundred bytes each, with room for long keys.
MAX_BATCH_BODY = 1024 * 1024


def tokens(instances: Iterable[Producer], environ: Mapping[str, str]) -> dict[str, str]:
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


def token_owner(tokens: Mapping[str, str], authorization: str | None) -> str | None:
    """The instance the bearer token belongs to; every token is compared, so the time taken names none of them."""
    scheme, _, presented = (authorization or "").partition(" ")
    owner = None
    for name, token in tokens.items():
        if hmac.compare_digest(token.encode(), presented.encode()) and scheme.lower() == "bearer" and presented:
            owner = name
    return owner


def run_event(event: object) -> dict[str, Any] | str:
    """`event` when it is a run event the contract allows, else the reason it is refused."""
    if not isinstance(event, dict):
        return "the body must be a JSON object"
    for key in ("workflow", "run_id"):
        if not (isinstance(event.get(key), str) and event[key]):
            return f"{key} must be non-empty text"
    if event.get("event") not in run_events.EVENTS:
        return f"event must be one of {', '.join(run_events.EVENTS)}"
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
