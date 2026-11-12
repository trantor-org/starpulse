"""What the reconcile pass decides from what GitHub lists: which deliveries to redeliver, and the inbox rows for the pull
request facts GitHub never sent.

A reconcile row is shaped like the webhook body that would have reported the fact, so the `events` consumer reads it with
the code it reads a delivery with, and its fact (and so its event id) is the one the delivery would have produced.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from starpulse.github.model.delivery import Delivery

__all__ = ["LOOKBACK_S", "SOURCE", "epoch", "pull_delivery", "redeliveries", "suite_delivery"]

SOURCE = "reconcile"
#: How far back a read with no cursor reaches: the retention of the inbox's rows.
LOOKBACK_S = 7 * 86400


def epoch(stamp: str) -> float:
    """The Unix time of an ISO-8601 timestamp as GitHub writes it."""
    return datetime.fromisoformat(stamp).timestamp()


def redeliveries(attempts: Iterable[dict[str, Any]], held: set[str]) -> list[int]:
    """The attempt to redeliver for each GUID in `attempts` that is not in `held`: its newest. A GUID with a redelivery
    among its attempts was already asked for, and is left alone."""
    by_guid: dict[str, list[dict[str, Any]]] = {}
    for attempt in attempts:
        by_guid.setdefault(attempt["guid"], []).append(attempt)
    return [
        max(tries, key=lambda attempt: epoch(attempt["delivered_at"]))["id"]
        for guid, tries in by_guid.items()
        if guid not in held and not any(attempt["redelivery"] for attempt in tries)
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
    user = (pull.get("user") or {}).get("type")
    summary = {"number": number, "merged": merged, "merge_commit_sha": merge, "head": {"sha": head}, "user": {"type": user}}
    return _delivery(f"reconcile:{repository}:{number}:{key}", "pull_request", repository, {"action": "closed", "pull_request": summary})


def suite_delivery(repository: str, number: int, head: str, suite: dict[str, Any]) -> Delivery | None:
    """The `check_suite` delivery that reports a finished suite on pull request `number`'s head; `None` for one unfinished."""
    if suite.get("status") != "completed" or not suite.get("conclusion") or not suite.get("id"):
        return None
    summary = {"id": suite["id"], "conclusion": suite["conclusion"], "pull_requests": [{"number": number}]}
    return _delivery(
        f"reconcile:{repository}:{number}:{head}:{suite['id']}", "check_suite", repository, {"action": "completed", "check_suite": summary}
    )
