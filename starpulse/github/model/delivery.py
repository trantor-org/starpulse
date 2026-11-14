"""What intake decides about one POST: refuse it with a status and a verdict, or admit it as a `Delivery` to save.

The order is the ADR's: a body over the cap, then the signature over the raw body (nothing parsed before it matches),
then the event allowlist, then the repository allowlist. Saving and the 202/503 that follows it belong to the listener.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass

from starpulse.github.model.github_config import GitHub

__all__ = ["EVENTS", "UNVERIFIED", "Delivery", "Refusal", "admit", "declared_length"]

#: The events a deployment saves; any other is answered 204 and counted as `other`.
EVENTS = frozenset(
    {
        "pull_request", "pull_request_review", "pull_request_review_comment", "push", "merge_group", "check_run",
        "check_suite", "workflow_job", "repository_dispatch", "create", "delete", "workflow_run", "merge_queue_entry",
        "release", "deploy_key", "deployment", "deployment_review", "deployment_status", "status",
    }
)  # fmt: skip
#: The event label of a request whose signature did not match: its header is not trusted.
UNVERIFIED = "unverified"
OTHER = "other"


@dataclass(frozen=True)
class Delivery:
    """A verified delivery of an allowed event from an accepted repository, as the inbox keeps it."""

    delivery_id: str
    event: str
    action: str
    repository: str
    body: bytes


@dataclass(frozen=True)
class Refusal:
    """A POST that is answered without saving: its HTTP status, its counter verdict and its counter event label."""

    status: int
    verdict: str
    event: str = UNVERIFIED


def declared_length(settings: GitHub, content_length: str | None) -> Refusal | None:
    """The refusal for a declared length that is missing, not a number, or over `max_body_bytes`."""
    if content_length is None or not (content_length.isascii() and content_length.isdigit()):
        return Refusal(400, "invalid")
    too_long = len(content_length) > len(str(settings.max_body_bytes)) or int(content_length) > settings.max_body_bytes
    return Refusal(413, "oversize") if too_long else None


def _signed(secret: bytes, body: bytes, presented: str) -> bool:
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(presented.encode(), expected.encode())


def _payload(body: bytes) -> dict[str, object] | None:
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def admit(settings: GitHub, secret: bytes, header: Callable[[str], str | None], body: bytes) -> Delivery | Refusal:
    """`body` as a `Delivery`, or the `Refusal` for the first step it fails; `header` reads a request header by name."""
    if not _signed(secret, body, header("X-Hub-Signature-256") or ""):
        return Refusal(401, "bad_signature")
    event = header("X-GitHub-Event") or ""
    if event not in EVENTS:
        return Refusal(204, "ignored", OTHER)
    delivery_id = header("X-GitHub-Delivery") or ""
    payload = _payload(body)
    if not delivery_id or payload is None:
        return Refusal(400, "invalid", event)
    repository = payload.get("repository")
    name = _text(repository.get("full_name")) if isinstance(repository, dict) else ""
    if not settings.accepts(name):
        return Refusal(204, "foreign_repository", event)
    return Delivery(delivery_id, event, _text(payload.get("action")), name, body)
