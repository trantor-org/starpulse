"""The `events` consumer: each saved delivery that reports a pull request fact becomes one machine event, and one that reports a workflow run
becomes one run event.

`consume` makes one pass over the deliveries due; `run` repeats it on a thread until it is told to stop. A delivery is
done once the ingest accepts its event (a repeat of the fact is accepted and collapses on the event id), is retried
with a growing wait while the ingest is out of reach or the pull request is not yet linked to a task, and is dead at
once when the ingest refuses the event for good.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starpulse.github.adapters.inbound import reconcile
from starpulse.github.adapters.inbound.listener import INBOX_FILE
from starpulse.github.adapters.outbound.cursors import SqlCursors
from starpulse.github.adapters.outbound.inbox import Migrate, SqlInbox
from starpulse.github.adapters.outbound.queue import SqlQueue
from starpulse.github.adapters.outbound.reconciled import Reconciled
from starpulse.github.adapters.outbound.rest import connect_client
from starpulse.github.model.events import CONSUMER, REFUSED, cloudevent, facts_of, run_event_of
from starpulse.github.ports.events import Entry, Ingest, Links, Queue

__all__ = ["consume", "open_queue", "run", "start"]

logger = logging.getLogger(__name__)

#: Seconds between two passes, and between two purges.
_PASS_S = 1.0
_PURGE_S = 3600.0


def _post(queue: Queue, ingest: Ingest, delivery_id: str, events: list[dict[str, Any]]) -> None:
    for event in events:
        status = ingest.post(event)
        if status != 201:
            queue.fail(delivery_id, f"ingest answered {status}" if status else "ingest unreachable", fatal=status in REFUSED)
            return
    queue.complete(delivery_id)


def _one(queue: Queue, ingest: Ingest, links: Links, entry: Entry) -> None:
    delivery_id = entry.delivery.delivery_id
    run = run_event_of(entry.delivery.event, entry.delivery.body)
    if run is not None:
        return _post(queue, ingest, delivery_id, [run])
    facts = facts_of(entry.delivery.event, entry.delivery.body)
    if not facts:
        return queue.skip(delivery_id, "no-fact")
    if all(fact.bot for fact in facts):
        return queue.skip(delivery_id, "no-task")
    tasks = [(fact, links.task_for(fact.repository, fact.number)) for fact in facts]
    linked = [(fact, task) for fact, task in tasks if task is not None]
    if not linked:
        queue.fail(delivery_id, "no-task", exhausted="skipped")
        return
    _post(queue, ingest, delivery_id, [cloudevent(fact, task) for fact, task in linked])


def consume(queue: Queue, ingest: Ingest, links: Links) -> None:
    """Try each delivery due now once, then return."""
    for entry in queue.claim():
        try:
            _one(queue, ingest, links, entry)
        except Exception:
            logger.exception("github events: %s", entry.delivery.delivery_id)
            queue.fail(entry.delivery.delivery_id, "consumer error")


def run(queue: Queue, ingest: Ingest, links: Links, stop: threading.Event, purge: Callable[[], None]) -> None:
    """Consume until `stop` is set, purging the rows past their retention once an hour."""
    purged = 0.0
    while not stop.is_set():
        try:
            consume(queue, ingest, links)
            if time.monotonic() - purged >= _PURGE_S:
                purge()
                purged = time.monotonic()
        except Exception:
            logger.exception("github events: pass failed")
        stop.wait(_PASS_S)


def open_queue(config: Any, base: Path, migrate: Migrate) -> tuple[SqlInbox, SqlQueue]:
    """The inbox `[github]` names, migrated, and the `events` consumer's queue over it."""
    settings = config.github
    if settings is None:
        raise ValueError("no [github] table in the config")
    inbox = SqlInbox(settings.database_url or f"sqlite:///{(base / INBOX_FILE).resolve()}", migrate)
    return inbox, SqlQueue(inbox.engine, CONSUMER)


def start(
    config: Any, base: Path, stop: threading.Event, migrate: Migrate, ingest: Ingest, links: Links
) -> Callable[[], None]:
    """The `github-events` context: consume the inbox `[github]` names on a thread until `stop` is set. The listener's
    container holds no producer token, so this runs apart from it, over the same inbox, with the `ingest` that holds it.

    With `[github] reconcile_token_env` it also reconciles the inbox against GitHub on a thread of its own, at start and
    every `reconcile_interval_s`, so a slow GitHub never holds the consumer.

    Returns the context's reload, which has nothing to re-read."""
    inbox, queue = open_queue(config, base, migrate)
    settings = config.github

    def work() -> None:
        try:
            run(queue, ingest, links, stop, queue.purge)
        finally:
            inbox.engine.dispose()

    def reconciles() -> None:
        client = connect_client(lambda: os.environ.get(settings.reconcile_token_env or ""))
        cursors, counted = SqlCursors(inbox.engine), Reconciled()
        reconcile.run(
            lambda: reconcile.reconcile(client, inbox, cursors, settings, counted, time.time),
            stop,
            settings.reconcile_interval_s,
        )

    threading.Thread(target=work, name="github-events", daemon=True).start()
    if settings.reconcile_token_env:
        threading.Thread(target=reconciles, name="github-reconcile", daemon=True).start()
    return lambda: None
