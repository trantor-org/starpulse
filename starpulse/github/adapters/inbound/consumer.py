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

from starpulse.github.adapters.inbound.head_checks import MACHINE as CHECKS_MACHINE
from starpulse.github.adapters.inbound.head_checks import HeadChecks
from starpulse.github.adapters.inbound.listener import INBOX_FILE
from starpulse.github.adapters.outbound.head_reader import GitHubReader
from starpulse.github.adapters.outbound.inbox import Migrate, SqlInbox
from starpulse.github.adapters.outbound.queue import SqlQueue
from starpulse.github.adapters.outbound.rest import connect
from starpulse.github.model.events import CONSUMER, REFUSED, cloudevent, facts_of, run_event_of
from starpulse.github.ports.events import Entry, Ingest, Links, Queue

__all__ = ["consume", "open_queue", "run", "start"]

logger = logging.getLogger(__name__)

#: Seconds between two passes, and between two purges.
_PASS_S = 1.0
_PURGE_S = 3600.0


def _post(queue: Queue, ingest: Ingest, delivery_id: str, events: list[dict[str, Any]]) -> bool:
    for event in events:
        status = ingest.post(event)
        if status != 201:
            queue.fail(delivery_id, f"ingest answered {status}" if status else "ingest unreachable", fatal=status in REFUSED)
            return False
    queue.complete(delivery_id)
    return True


def _one(queue: Queue, ingest: Ingest, links: Links, entry: Entry, checks: HeadChecks | None = None) -> None:
    delivery_id = entry.delivery.delivery_id
    run = run_event_of(entry.delivery.event, entry.delivery.body)
    if run is not None:
        _post(queue, ingest, delivery_id, [run])
        return
    facts = facts_of(entry.delivery.event, entry.delivery.body)
    planned = None
    if checks is not None:
        try:
            planned = checks.plan(entry.delivery.event, entry.delivery.body, links)
        except OSError as exc:  # GitHub refused a read the rollup needs: retried, nothing posted
            queue.fail(delivery_id, f"github read failed: {exc}")
            return
        facts = [fact for fact in facts if fact.event != "CHECKS_PASSED"]  # a suite's success is not the required set's
    extra = planned.events if planned else []
    bots = bool(facts) and all(fact.bot for fact in facts)
    if bots:
        facts = []
    if not facts and not extra:
        queue.skip(delivery_id, "no-task" if bots else "no-fact")
        return
    tasks = [(fact, links.task_for(fact.repository, fact.number)) for fact in facts]
    linked = [(fact, task) for fact, task in tasks if task is not None]
    if not linked and not extra:
        queue.fail(delivery_id, "no-task", exhausted="skipped")
        return
    if _post(queue, ingest, delivery_id, [cloudevent(fact, task) for fact, task in linked] + extra) and planned:
        planned.settle()


def consume(queue: Queue, ingest: Ingest, links: Links, checks: HeadChecks | None = None) -> None:
    """Try each delivery due now once, then return."""
    for entry in queue.claim():
        try:
            _one(queue, ingest, links, entry, checks)
        except Exception:
            logger.exception("github events: %s", entry.delivery.delivery_id)
            queue.fail(entry.delivery.delivery_id, "consumer error")


def run(
    queue: Queue,
    ingest: Ingest,
    links: Links,
    stop: threading.Event,
    purge: Callable[[], None],
    checks: HeadChecks | None = None,
) -> None:
    """Consume until `stop` is set, purging the rows past their retention once an hour."""
    purged = 0.0
    while not stop.is_set():
        try:
            consume(queue, ingest, links, checks)
            if time.monotonic() - purged >= _PURGE_S:
                purge()
                purged = time.monotonic()
        except Exception:
            logger.exception("github events: pass failed")
        stop.wait(_PASS_S)


def open_queue(config: Any, base: Path, migrate: Migrate, consumer: str = CONSUMER) -> tuple[SqlInbox, SqlQueue]:
    """The inbox `[github]` names, migrated, and `consumer`'s queue over it."""
    settings = config.github
    if settings is None:
        raise ValueError("no [github] table in the config")
    inbox = SqlInbox(settings.database_url or f"sqlite:///{(base / INBOX_FILE).resolve()}", migrate)
    return inbox, SqlQueue(inbox.engine, consumer)


def start(
    config: Any, base: Path, stop: threading.Event, migrate: Migrate, ingest: Ingest, links: Links
) -> Callable[[], None]:
    """The `github-events` context: consume the inbox `[github]` names on a thread until `stop` is set. The listener's
    container holds no producer token, so this runs apart from it, over the same inbox, with the `ingest` that holds it.

    The reconcile against GitHub is the sweeper's `github` kind, not a thread here. When the `github` producer may write
    the `pr-checks` machine it also publishes each check delivery and its head's rollup (`HeadChecks`), reading GitHub
    with `GITHUB_TOKEN` or `GH_TOKEN`, as the pull request adapter does.

    Returns the context's reload, which has nothing to re-read."""
    inbox, queue = open_queue(config, base, migrate)
    publishes_checks = any(CHECKS_MACHINE in p.machines for p in config.producers if p.name == "github")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    checks = HeadChecks(GitHubReader(connect(token))) if publishes_checks else None

    def work() -> None:
        try:
            run(queue, ingest, links, stop, queue.purge, checks)
        finally:
            inbox.engine.dispose()

    threading.Thread(target=work, name="github-events", daemon=True).start()
    return lambda: None
