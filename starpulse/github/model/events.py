"""What the `events` consumer makes of a saved delivery: the pull request facts it reports, their event ids, the retry policy.

A delivery is a hint, never a delta: a fact names the pull request and the SHA or check suite it is about, and the event
id is derived from that fact so two deliveries of one fact, and a redelivery, collapse in the event log.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

__all__ = [
    "BUDGET", "CAP", "CONSUMER", "MACHINE", "REFUSED", "RETENTION", "SOURCE", "Fact", "backoff", "cloudevent", "event_id", "facts_of", "run_event_of",
]  # fmt: skip

SOURCE = "github"
MACHINE = "github-pull-request"
#: The consumer that turns deliveries into machine events.
CONSUMER = "events"
#: Failed attempts a delivery gets before it is dead (or, for a pull request still unlinked, skipped as `no-task`).
BUDGET = 10
#: The longest wait, in seconds, between two attempts.
CAP = 300
#: Seconds a done or skipped row is kept.
RETENTION = 7 * 86400
#: The ingest answers that no retry can repair: the event is invalid (400), forbidden (403) or too large (413).
REFUSED = frozenset({400, 403, 413})
_PASSED = frozenset({"success", "neutral", "skipped"})
_FAILED = frozenset({"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"})


def backoff(attempts: int) -> int:
    """Seconds to wait after `attempts` failed attempts."""
    return min(2**attempts, CAP)


@dataclass(frozen=True)
class Fact:
    """One thing GitHub said about a pull request: `event` is the machine event, `key` the SHA or check suite id it is about."""

    event: str
    repository: str
    number: int
    key: str
    bot: bool = False


def event_id(fact: Fact) -> str:
    """SHA-256 over the repository, pull request number, event type and key."""
    return hashlib.sha256("\n".join((fact.repository, str(fact.number), fact.event, fact.key)).encode()).hexdigest()


def cloudevent(fact: Fact, task: str) -> dict[str, Any]:
    """`fact` as the CloudEvent the ingest takes, moving `task` as the `github` actor."""
    return {
        "specversion": "1.0",
        "id": event_id(fact),
        "source": SOURCE,
        "type": fact.event,
        "subject": task,
        "machine": MACHINE,
        "actor": SOURCE,
        "data": {"repository": fact.repository, "pull_request": fact.number, "key": fact.key},
    }


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _number(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _pull_request(repository: str, action: str, payload: dict[str, Any]) -> list[Fact]:
    pull = _dict(payload.get("pull_request"))
    number = _number(pull.get("number"))
    head = _text(_dict(pull.get("head")).get("sha"))
    if number is None:
        return []
    bot = _text(_dict(pull.get("user")).get("type")) == "Bot"
    if action == "closed" and pull.get("merged") is True:
        merge = _text(pull.get("merge_commit_sha"))
        return [Fact("PR_MERGED", repository, number, merge, bot)] if merge else []
    named = {"opened": "PR_OPENED", "reopened": "PR_REOPENED", "closed": "PR_CLOSED"}.get(action)
    return [Fact(named, repository, number, head, bot)] if named and head else []


def _checks(repository: str, event: str, action: str, payload: dict[str, Any]) -> list[Fact]:
    """A suite's conclusion is the one verdict on its pull requests; a run that failed reports the failure early, and a
    run that passed says nothing about the suite."""
    thing = _dict(payload.get(event))
    suite = _dict(thing.get("check_suite")) if event == "check_run" else thing
    conclusion, key = _text(thing.get("conclusion")), suite.get("id")
    passed = conclusion in _PASSED and event == "check_suite"
    if action != "completed" or not (passed or conclusion in _FAILED) or _number(key) is None:
        return []
    named = "CHECKS_PASSED" if passed else "CHECKS_FAILED"
    pulls = thing.get("pull_requests")
    numbers = [_number(_dict(pull).get("number")) for pull in pulls] if isinstance(pulls, list) else []
    return [Fact(named, repository, number, str(key)) for number in numbers if number is not None]


def facts_of(event: str, body: bytes) -> list[Fact]:
    """The facts a delivery reports, read from its body alone; none when it reports no pull request fact."""
    try:
        payload = json.loads(body)
    except ValueError:
        return []
    payload = _dict(payload)
    repository = _text(_dict(payload.get("repository")).get("full_name"))
    action = _text(payload.get("action"))
    if not repository:
        return []
    if event == "pull_request":
        return _pull_request(repository, action, payload)
    if event in ("check_suite", "check_run"):
        return _checks(repository, event, action, payload)
    return []


#: A run's `status` before it completes, and each `conclusion` after, as the runs projection's status.
_RUN_STATUS = {"requested": "queued", "pending": "queued", "queued": "queued", "waiting": "queued", "in_progress": "running"}
_RUN_CONCLUSION = {
    "success": "succeeded", "neutral": "succeeded", "failure": "failed", "timed_out": "failed",
    "startup_failure": "failed", "cancelled": "aborted", "stale": "aborted", "action_required": "aborted",
    "skipped": "skipped",
}  # fmt: skip


def run_event_of(event: str, body: bytes) -> dict[str, Any] | None:
    """The run event a `workflow_run` delivery reports, as the CloudEvent the ingest takes; none for any other delivery,
    a body that is no run, or a status the projection has no name for. The event id is derived from the run, its attempt
    and its state, so a redelivery collapses and a re-run is another event."""
    if event != "workflow_run":
        return None
    try:
        payload = _dict(json.loads(body))
    except ValueError:
        return None
    run = _dict(payload.get("workflow_run"))
    repository = _text(_dict(payload.get("repository")).get("full_name"))
    run_id, path, state = _number(run.get("id")), _text(run.get("path")), _text(run.get("status"))
    conclusion = _text(run.get("conclusion"))
    done = state == "completed"
    mapped = (_RUN_CONCLUSION if done else _RUN_STATUS).get(conclusion if done else state)
    if not (repository and run_id and path and mapped):
        return None
    key = "\n".join((repository, str(run_id), str(run.get("run_attempt")), state, conclusion))
    return {
        "specversion": "1.0",
        "id": hashlib.sha256(key.encode()).hexdigest(),
        "source": SOURCE,
        "type": "StepFinished" if done else "StepStarted",
        "subject": str(run_id),
        "data": {"workflow": path.rsplit("/", 1)[-1], "status": mapped},
    }
