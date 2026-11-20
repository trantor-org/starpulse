"""The `pulls` consumer: each saved `pull_request` delivery writes the PR store's record, whether or not a task cites it.

A delivery carries the whole pull request, but each action writes only the fields the spec's Field Sources table
names for it, so an `edited` delivery never takes back a head a `synchronize` moved. An action with no row (`labeled`,
`assigned`) leaves the record alone. A pull request the store lacks is made from the whole payload first, as the machine
events make one.
"""

import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from starpulse.github.adapters.inbound.consumer import follow, open_queue
from starpulse.github.adapters.outbound.inbox import Migrate
from starpulse.github.model.delivery import Delivery
from starpulse.github.ports.events import OpenWatch, Queue, Stop
from starpulse.pulls.adapters.outbound.pull_events import Record, bare_detail, opened
from starpulse.pulls.adapters.outbound.pulls import PullStore

__all__ = ["CONSUMER", "apply", "consume", "start"]

logger = logging.getLogger(__name__)

CONSUMER = "pulls"

Delta = Callable[[Record, Mapping[str, Any], float], Record]


def _detail(record: Record, at: float) -> Record:
    return record["detail"] or bare_detail(at)


def _created(record: Record, pull: Mapping[str, Any], at: float) -> Record:
    detail = _detail(record, at)
    return {"detail": detail | {"ci": detail["ci"] | {"createdAt": pull["created_at"]}}}


def _state(_record: Record, pull: Mapping[str, Any], _at: float) -> Record:
    return {"state": "MERGED" if pull.get("merged") else str(pull["state"]).upper()}


def _draft(_record: Record, pull: Mapping[str, Any], _at: float) -> Record:
    return {"isDraft": bool(pull["draft"])}


def _text(_record: Record, pull: Mapping[str, Any], _at: float) -> Record:
    return {"title": pull["title"], "body": pull["body"] or "", "updatedAt": pull["updated_at"]}


def _base(_record: Record, pull: Mapping[str, Any], _at: float) -> Record:
    return {"baseRefName": pull["base"]["ref"]}


def _head_ref(_record: Record, pull: Mapping[str, Any], _at: float) -> Record:
    return {"headRefName": pull["head"]["ref"]}


def _head(record: Record, pull: Mapping[str, Any], _at: float) -> Record:
    sha = pull["head"]["sha"]
    return {"headRefOid": sha} | ({} if sha == record["headRefOid"] else {"requiredChecks": []})  # the old head's verdicts


def _merge(record: Record, pull: Mapping[str, Any], at: float) -> Record:
    merged = bool(pull.get("merged"))
    stamp, sha = (pull["merged_at"], pull["merge_commit_sha"]) if merged else (None, None)
    detail = _detail(record, at)
    ci = detail["ci"] | {"merged": merged, "mergedAt": stamp}
    return {"mergedAt": stamp, "mergeSha": sha, "detail": detail | {"mergedAt": stamp, "mergeSha": sha, "ci": ci}}


def _queued(flag: bool) -> Delta:
    def delta(record: Record, _pull: Mapping[str, Any], at: float) -> Record:
        return {"detail": _detail(record, at) | {"queued": flag}}  # no column holds it: `detail` does

    return delta


_OPENED: tuple[Delta, ...] = (_created, _state, _draft, _text, _base, _head_ref, _head)
#: The fields each action writes, by the Field Sources rows of its `pull_request` event.
_ACTIONS: dict[str, tuple[Delta, ...]] = {
    "opened": _OPENED,
    "reopened": (_state, _head),
    "edited": (_text, _base),
    "synchronize": (_head,),
    "ready_for_review": (_draft,),
    "converted_to_draft": (_draft,),
    "closed": (_state, _merge),
    "enqueued": (_queued(True),),
    "dequeued": (_queued(False),),
}


def apply(store: PullStore, delivery: Delivery, now: float) -> bool:
    """Write the fields `delivery`'s action names to its pull request's record, and say whether it wrote."""
    deltas = _ACTIONS.get(delivery.action)
    if delivery.event != "pull_request" or deltas is None:
        return False
    pull = json.loads(delivery.body)["pull_request"]
    found = store.find(delivery.repository, pull["number"], detailed=True)
    record = found[0] if found else opened(delivery.repository, pull["number"], pull["body"] or "", now)
    for delta in deltas if found else (*_OPENED, *deltas):
        record = record | delta(record, pull, now)
    store.save([record])
    return True


def consume(queue: Queue, store: PullStore, clock: Callable[[], float] = time.time) -> None:
    """Apply each delivery due now once, then return: a delivery that applies or has no row is done, one that cannot be
    read is retried and then dead."""
    for entry in queue.claim():
        delivery_id = entry.delivery.delivery_id
        try:
            wrote = apply(store, entry.delivery, clock())
        except Exception:
            logger.exception("github pulls: %s", delivery_id)
            queue.fail(delivery_id, "consumer error")
            continue
        if wrote:
            queue.complete(delivery_id)
        else:
            queue.skip(delivery_id, "no-field")


def start(
    config: Any, base: Path, stop: Stop, store: PullStore, migrate: Migrate, open_watch: OpenWatch
) -> None:
    """Follow the inbox `[github]` names on a thread until `stop` is set, with a cursor of its own beside the `events` one."""
    inbox, queue = open_queue(config, base, migrate, CONSUMER)
    url = inbox.engine.url
    watch = open_watch(url.database) if url.get_backend_name() == "sqlite" and url.database else None

    def work() -> None:
        try:
            follow(queue, stop, watch, lambda: consume(queue, store), "github pulls")
        finally:
            inbox.engine.dispose()
            if watch is not None:
                watch.close()

    threading.Thread(target=work, name="github-pulls", daemon=True).start()
