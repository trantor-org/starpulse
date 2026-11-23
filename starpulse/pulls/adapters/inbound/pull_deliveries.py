"""The `pulls` consumer: each saved delivery the spec's Field Sources table names writes the PR store's record, whether
or not a task cites it.

A `pull_request` delivery carries the whole pull request, but each action writes only the fields the spec's Field Sources table
names for it, so an `edited` delivery never takes back a head a `synchronize` moved. An action with no row (`labeled`,
`assigned`) leaves the record alone. A pull request the store lacks is made from the whole payload first, as the machine
events make one. The other events (`pull_facts`) write the checks, threads and CI trail.
"""

import json
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from functools import partial
from typing import Any

from sqlalchemy.engine import Engine

from starpulse.github.adapters.inbound.consumer import follow
from starpulse.github.adapters.outbound.app_jwt import app_jwt
from starpulse.github.adapters.outbound.cursors import SqlCursors
from starpulse.github.adapters.outbound.queue import SqlQueue
from starpulse.github.adapters.outbound.rest import connect_client
from starpulse.github.model.delivery import Delivery
from starpulse.github.model.reconcile import epoch
from starpulse.github.ports.events import OpenWatch, Queue, Stop
from starpulse.pulls.adapters.inbound.pull_facts import FACTS, forced_push
from starpulse.pulls.adapters.outbound.pull_events import Record, bare_detail, opened, reopened
from starpulse.pulls.adapters.outbound.pull_reads import READ_EVENTS, PullReads, refresh
from starpulse.pulls.adapters.outbound.pulls import PullStore

__all__ = ["CONSUMER", "READS", "URGENT", "apply", "consume", "consume_reads", "start"]

logger = logging.getLogger(__name__)

CONSUMER = "pulls"
#: The consumer of the `READ_EVENTS` deliveries: a push's compare read per open pull request takes minutes under load,
#: so it runs on a cursor and thread of its own, never ahead of a delivery that writes.
READS = "pull-reads"
#: The `(event, action)` deliveries claimed ahead of every older one: a merge moves its task at once.
URGENT = (("pull_request", "closed"),)

Delta = Callable[[Record, Mapping[str, Any], float], Record]


def _detail(record: Record, at: float) -> Record:
    return record["detail"] or bare_detail(at)


def _created(record: Record, pull: Mapping[str, Any], at: float) -> Record:
    detail = _detail(record, at)
    return {"detail": detail | {"ci": detail["ci"] | {"createdAt": pull["created_at"]}}}


def _state(_record: Record, pull: Mapping[str, Any], _at: float) -> Record:
    if pull.get("merged"):
        return {"state": "MERGED"}
    if "state" not in pull:  # a body without a state says nothing about it: the stored one stands
        return {}
    return {"state": str(pull["state"]).upper()}


def _draft(record: Record, pull: Mapping[str, Any], at: float) -> Record:
    # stamped so the store refuses a read begun before this delivery, saved after it, that still says draft
    return {"isDraft": bool(pull["draft"]), "fetchedAt": max(at, record["fetchedAt"])}


def _text(_record: Record, pull: Mapping[str, Any], _at: float) -> Record:
    return {"title": pull["title"], "body": pull["body"] or "", "updatedAt": pull["updated_at"]}


def _base(_record: Record, pull: Mapping[str, Any], _at: float) -> Record:
    return {"baseRefName": pull["base"]["ref"]}


def _head_ref(_record: Record, pull: Mapping[str, Any], _at: float) -> Record:
    return {"headRefName": pull["head"]["ref"]}


def _head(record: Record, pull: Mapping[str, Any], _at: float) -> Record:
    sha = pull["head"]["sha"]
    if sha == record["headRefOid"]:
        return {"headRefOid": sha}
    forgotten = [{"name": check["name"], "result": "pending"} for check in record["requiredChecks"]]  # the old head's verdicts
    return {"headRefOid": sha, "requiredChecks": forgotten}


def _merge(record: Record, pull: Mapping[str, Any], at: float) -> Record:
    merged = bool(pull.get("merged"))
    # A reduced reconcile body may name no merge time: the stored one stands.
    stamp, sha = (pull.get("merged_at", record["mergedAt"]), pull.get("merge_commit_sha", record["mergeSha"])) if merged else (None, None)
    detail = _detail(record, at)
    shut = record["state"] == "CLOSED"  # `_state` ran first; an open pull request is not closed
    closed = {"closed": shut, "closedAt": pull["closed_at"] if shut else None}
    ci = detail["ci"] | {"merged": merged, "mergedAt": stamp} | closed
    return {"mergedAt": stamp, "mergeSha": sha, "detail": detail | {"mergedAt": stamp, "mergeSha": sha, "ci": ci}}


def _queued(flag: bool) -> Delta:
    def delta(record: Record, _pull: Mapping[str, Any], at: float) -> Record:
        return {"detail": _detail(record, at) | {"queued": flag}}  # no column holds it: `detail` does

    return delta


_OPENED: tuple[Delta, ...] = (_created, _state, _draft, _text, _base, _head_ref, _head)
#: The fields each action writes, by the Field Sources rows of its `pull_request` event.
_ACTIONS: dict[str, tuple[Delta, ...]] = {
    "opened": _OPENED,
    "reopened": (reopened, _head),
    "edited": (_text, _base),
    "synchronize": (_head,),
    "ready_for_review": (_draft,),
    "converted_to_draft": (_draft,),
    "closed": (_state, _merge),
    "reconciled": (_state, _draft, _text, _base, _head_ref, _head, _merge),  # a reconcile row: the whole listing, not one action
    "enqueued": (_queued(True),),
    "dequeued": (_queued(False),),
}


def _outdated(record: Record, pull: Mapping[str, Any]) -> bool:
    """Whether a listing snapshot says open for a record closed or merged at or after the snapshot's own `updated_at`."""
    if record["state"] == "OPEN" or str(pull.get("state", "")).upper() != "OPEN":
        return False
    closed = record["mergedAt"] or record["detail"]["ci"].get("closedAt")
    return bool(closed) and epoch(pull["updated_at"]) <= epoch(closed)


def _main_checked(delivery: Delivery) -> bool:
    """Whether the delivery reports a finished workflow run or check suite on the repository's default branch."""
    if delivery.event not in ("workflow_run", "check_suite") or delivery.action != "completed":
        return False
    try:
        body = json.loads(delivery.body)
        return body[delivery.event]["head_branch"] == body["repository"]["default_branch"]
    except KeyError, TypeError, ValueError:
        return False


def apply(
    store: PullStore,
    delivery: Delivery,
    now: float,
    reads: PullReads | None = None,
    amended: Callable[[], None] | None = None,
) -> bool:
    """Write the fields `delivery`'s event and action name to the records they concern, and say whether it wrote. `amended` is
    called once the record is written, ahead of the reads that refresh it."""
    if delivery.event in READ_EVENTS:  # its reads are `consume_reads`'s
        return delivery.event == "push" and forced_push(store, delivery, json.loads(delivery.body), now)
    if (fact := FACTS.get(delivery.event)) is not None:
        return fact(store, delivery, json.loads(delivery.body), now)
    deltas = _ACTIONS.get(delivery.action)
    if delivery.event != "pull_request" or deltas is None:
        return False
    pull = json.loads(delivery.body)["pull_request"]

    def change(found: Record | None) -> Record | None:
        if not found and "created_at" not in pull:  # a reduced reconcile body cannot open a record
            logger.info("github pulls: %s: no record and a reduced body", delivery.delivery_id)
            return None
        if found and delivery.action == "opened" and found["state"] != "OPEN":
            return None  # an `opened` applied late: only `reopened` moves a closed or merged record back to open
        if found and delivery.action == "reconciled" and _outdated(found, pull):
            return None  # a listing read before the close, applied after it: only a later snapshot reopens
        record = found or opened(delivery.repository, pull["number"], pull["body"] or "", now)
        for delta in deltas if found else (*_OPENED, *deltas):
            record = record | delta(record, pull, now)
        return record

    if not store.amend(delivery.repository, pull["number"], change):
        return False
    if amended is not None:
        amended()
    if reads is not None:
        refresh(store, reads, delivery, now)
    return True


def consume(
    queue: Queue,
    store: PullStore,
    clock: Callable[[], float] = time.time,
    reads: PullReads | None = None,
    merged: Callable[[float], None] | None = None,
    checked: Callable[[], None] | None = None,
) -> None:
    """Apply each delivery due now once, then return: a delivery that applies or has no row is done, one that cannot be
    read is retried and then dead. An `URGENT` delivery's write is handed to `merged` with the time it was received,
    before its refresh reads and the next delivery. A finished checks run on the default branch calls `checked`. A
    `READ_EVENTS` delivery makes no read here (`consume_reads` does); `apply` writes only its force push."""
    for entry in queue.claim():
        delivery = entry.delivery
        delivery_id = delivery.delivery_id
        urgent = (delivery.event, delivery.action) in URGENT
        handover = partial(merged, entry.received_at) if merged is not None and urgent else None
        try:
            if checked is not None and _main_checked(delivery):
                checked()
                queue.complete(delivery_id)
                continue
            wrote = apply(store, delivery, clock(), reads, handover)
        except Exception:
            logger.exception("github pulls: %s", delivery_id)
            queue.fail(delivery_id, "consumer error")
            continue
        if wrote:
            queue.complete(delivery_id)
        else:
            queue.skip(delivery_id, "no-field")


def consume_reads(queue: Queue, store: PullStore, reads: PullReads, clock: Callable[[], float] = time.time) -> None:
    """Make the reads each `READ_EVENTS` delivery due now names, once, then return: one GitHub refuses is retried and
    then dead."""
    for entry in queue.claim():
        try:
            refresh(store, reads, entry.delivery, clock())
        except Exception:
            logger.exception("github pull reads: %s", entry.delivery.delivery_id)
            queue.fail(entry.delivery.delivery_id, "consumer error")
        else:
            queue.complete(entry.delivery.delivery_id)


def start(
    config: Any,
    engine: Engine,
    stop: Stop,
    store: PullStore,
    open_watch: OpenWatch,
    merged: Callable[[float], None] | None = None,
    checked: Callable[[], None] | None = None,
) -> None:
    """Follow the inbox in the main store `engine` opens on a thread until `stop` is set, with a cursor of its own beside the
    `events` one, handing each `URGENT` delivery's write to `merged` and each finished main checks run to `checked` (`consume`). With a token, a second
    thread and cursor (`READS`) make the push and ruleset reads (`consume_reads`) with a client of its own; the store's owner disposes `engine`."""
    url = engine.url
    token_env = config.github.reconcile_token_env

    def thread(name: str, queue: SqlQueue, step: Callable[[], None]) -> None:
        watch = open_watch(url.database) if url.get_backend_name() == "sqlite" and url.database else None

        def work() -> None:
            try:
                follow(queue, stop, watch, step, name)
            finally:
                if watch is not None:
                    watch.close()

        threading.Thread(target=work, name=name.replace(" ", "-"), daemon=True).start()

    def connected() -> PullReads:
        return PullReads(connect_client(lambda: os.environ.get(token_env or ""), app_jwt), SqlCursors(engine))

    reads = connected() if token_env else None
    queue = SqlQueue(engine, CONSUMER, urgent=URGENT)
    thread("github pulls", queue, lambda: consume(queue, store, reads=reads, merged=merged, checked=checked))
    if reads is not None:
        reading, own = SqlQueue(engine, READS, only=READ_EVENTS), connected()
        thread("github pull reads", reading, lambda: consume_reads(reading, store, own))
