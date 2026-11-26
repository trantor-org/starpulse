"""What the reconcile pass decides from what GitHub lists: which deliveries to redeliver, and the inbox rows for the pull
request facts GitHub never sent.

A reconcile row is shaped like the webhook body that would have reported the fact, so the `events` consumer reads it with
the code it reads a delivery with, and its fact (and so its event id) is the one the delivery would have produced.
"""

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from starpulse.github.model.delivery import Delivery

__all__ = ["EARLY_S", "LATE_S", "LOOKBACK_S", "SETTLE_S", "SOURCE", "epoch", "pull_delivery", "redeliveries", "suite_delivery", "update_delivery"]

SOURCE = "reconcile"
#: How far back a read with no cursor reaches: the retention of the inbox's rows.
LOOKBACK_S = 7 * 86400
#: The window around a fact's GitHub timestamp in which a webhook row reporting it counts as its delivery: clock skew
#: before, delivery latency after. A row outside it leaves the fact to be inserted, which the event id collapses.
EARLY_S = 300
LATE_S = 900
#: How long after a fact its webhook may still be in flight: a fact younger than this is saved but not counted as a correction.
SETTLE_S = 60


def epoch(stamp: str) -> float:
    """The Unix time of an ISO-8601 timestamp as GitHub writes it."""
    return datetime.fromisoformat(stamp).timestamp()


def redeliveries(attempts: Iterable[dict[str, Any]], held: set[str]) -> list[dict[str, Any]]:
    """The attempt to redeliver for each GUID in `attempts` that is not in `held`: its newest, unless one of its attempts
    was answered 2xx, which the listener gives only to a delivery it saved or chose to ignore. A failed redelivery is
    asked again: it is a new attempt past the pass's cursor, so the GUID is asked again each pass until one attempt is
    answered."""
    by_guid: dict[str, list[dict[str, Any]]] = {}
    for attempt in attempts:
        by_guid.setdefault(attempt["guid"], []).append(attempt)
    return [
        max(tries, key=lambda attempt: epoch(attempt["delivered_at"]))
        for guid, tries in by_guid.items()
        if guid not in held and not any(200 <= attempt["status_code"] < 300 for attempt in tries)
    ]


def _delivery(delivery_id: str, event: str, repository: str, payload: dict[str, Any]) -> Delivery:
    body = json.dumps({"repository": {"full_name": repository}} | payload).encode()
    return Delivery(delivery_id, event, payload["action"], repository, body)


def pull_delivery(repository: str, pull: dict[str, Any]) -> Delivery | None:
    """The `pull_request` delivery that reports a closed pull request as merged or not; `None` for one still open."""
    number = pull.get("number")
    head = (pull.get("head") or {}).get("sha")
    merged = pull.get("merged_at") is not None
    merge = pull.get("merge_commit_sha")
    key = merge if merged else head
    if pull.get("state") != "closed" or not number or not key:
        return None
    payload = {"action": "closed", "number": number, "pull_request": pull | {"merged": merged}}
    return _delivery(f"reconcile:{repository}:{number}:{key}:closed", "pull_request", repository, payload)


def update_delivery(repository: str, pull: dict[str, Any]) -> Delivery | None:
    """The `pull_request` delivery that reports a pull request as the listing shows it, whatever its state; the `reconciled`
    action names no fact, so only the `pulls` consumer reads it. `None` for a listing with no number."""
    number = pull.get("number")
    if not number or not pull.get("updated_at"):
        return None
    payload = {"action": "reconciled", "number": number, "pull_request": pull | {"merged": pull.get("merged_at") is not None}}
    return _delivery(f"reconcile:{repository}:{number}:{pull['updated_at']}:updated", "pull_request", repository, payload)


def suite_delivery(repository: str, number: int, head: str, suite: dict[str, Any]) -> Delivery | None:
    """The `check_suite` delivery that reports a finished suite on pull request `number`'s head; `None` for one unfinished."""
    if suite.get("status") != "completed" or not suite.get("conclusion") or not suite.get("id"):
        return None
    kept = {key: suite[key] for key in ("id", "app", "status", "conclusion", "created_at", "updated_at") if key in suite}
    summary = kept | {"head_sha": head, "pull_requests": [{"number": number}]}
    return _delivery(
        f"reconcile:{repository}:{number}:{head}:{suite['id']}", "check_suite", repository, {"action": "completed", "check_suite": summary}
    )
