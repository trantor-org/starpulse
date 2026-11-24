"""The `events` consumer: each saved delivery that reports a pull request fact becomes one machine event, and one that reports a workflow run
becomes one run event.

`consume` makes one pass over the deliveries due; `run` repeats it on each commit to the store until it is told to stop.
A delivery is done once the ingest accepts its event (a repeat of the fact is accepted and collapses on the event id),
is retried with a growing wait while the ingest is out of reach or the pull request is not yet linked to a task, and is
dead at once when the ingest refuses the event for good.
"""

import logging
import os
import selectors
import threading
from collections.abc import Callable
from typing import Any

from sqlalchemy.engine import Engine

from starpulse.github.adapters.inbound.head_checks import MACHINE as CHECKS_MACHINE
from starpulse.github.adapters.inbound.head_checks import HeadChecks
from starpulse.github.adapters.outbound.head_reader import GitHubReader
from starpulse.github.adapters.outbound.queue import SqlQueue
from starpulse.github.adapters.outbound.rest import RateLimited, connect
from starpulse.github.model.events import CONSUMER, HANDLED, REFUSED, cloudevent, facts_of, run_event_of
from starpulse.github.ports.events import Entry, Ingest, Links, OpenWatch, Queue, Stop, Watch

__all__ = ["consume", "follow", "run", "start"]

logger = logging.getLogger(__name__)

RETRY_S = 1.0
FALLBACK_S = 3600.0

def _post(queue: Queue, ingest: Ingest, delivery_id: str, events: list[dict[str, Any]]) -> bool:
    for event in events:
        status = ingest.post(event)
        if status != 201:
            queue.fail(delivery_id, f"ingest answered {status}" if status else "ingest unreachable", fatal=status in REFUSED)
            return False
    queue.complete(delivery_id)
    return True


def _one(
    queue: Queue, ingest: Ingest, links: Links, entry: Entry, checks: HeadChecks | None = None, resync: Callable[[str, bytes], None] | None = None
) -> None:
    delivery_id = entry.delivery.delivery_id
    if resync is not None:
        resync(entry.delivery.event, entry.delivery.body)
    run = run_event_of(entry.delivery.event, entry.delivery.body)
    if run is not None:
        _post(queue, ingest, delivery_id, [run])
        return
    facts = facts_of(entry.delivery.event, entry.delivery.body)
    planned = None
    if checks is not None:
        try:
            planned = checks.plan(entry.delivery.event, entry.delivery.body, links)
        except RateLimited as exc:  # the quota is spent: no attempt is spent, and no read is made until it resets
            queue.defer(delivery_id, f"github rate limited: {exc}", exc.until)
            return
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


def consume(
    queue: Queue, ingest: Ingest, links: Links, checks: HeadChecks | None = None, resync: Callable[[str, bytes], None] | None = None
) -> None:
    """Try each delivery due now once, then return; the pass records its outcomes in one transaction."""
    entries = queue.claim()
    with queue.batch():
        for entry in entries:
            try:
                _one(queue, ingest, links, entry, checks, resync)
            except Exception:
                logger.exception("github events: %s", entry.delivery.delivery_id)
                queue.fail(entry.delivery.delivery_id, "consumer error")


def run(
    queue: Queue,
    ingest: Ingest,
    links: Links,
    stop: Stop,
    watch: Watch | None,
    checks: HeadChecks | None = None,
    resync: Callable[[str, bytes], None] | None = None,
) -> None:
    """Consume once, then again whenever the inbox commits (`watch`) or a retry falls due, until `stop` is set."""
    follow(queue, stop, watch, lambda: consume(queue, ingest, links, checks, resync), "github events")


def follow(queue: Queue, stop: Stop, watch: Watch | None, step: Callable[[], None], name: str) -> None:
    """Call `step` once, then again whenever the inbox commits (`watch`) or a retry of `queue` falls due, until `stop`
    is set. `name` prefixes the log lines of the consumer.

    The watch fires on any write to the store, this consumer's own included, so a pass runs only when `queue.look` shows
    a newer inbox row than the last pass saw, or a delivery due now; any other commit costs that one read. A look reads
    under the write lock, so it waits for a commit the watch announced before it is visible. Without a watch (a Postgres
    store, or a platform with neither inotify nor kqueue) a pass runs every `FALLBACK_S`, and says so once."""
    stopped, signal = os.pipe()

    def wake() -> None:
        os.write(signal, b"x")

    stop.listen(wake)
    selector = selectors.DefaultSelector()
    selector.register(stopped, selectors.EVENT_READ)
    if watch is None:
        logger.warning("%s: no file watch on the inbox; consuming every %ss", name, FALLBACK_S)
    else:
        selector.register(watch.fileno(), selectors.EVENT_READ)
    seen = None
    try:
        while not stop.is_set():
            wait = None if watch else FALLBACK_S
            try:
                head, due = queue.look()
                if head != seen or due == 0:
                    seen = head  # read before the pass, so a row saved during it runs the next
                    step()
                    due = queue.due_in()
                if due is not None:
                    wait = due if wait is None else min(wait, due)
            except Exception:
                logger.exception("%s: pass failed", name)
                seen, wait = None, RETRY_S
            selector.select(wait)
            if watch is not None:
                watch.drain()
    finally:
        stop.unlisten(wake)
        selector.close()
        os.close(stopped)
        os.close(signal)


def start(
    config: Any, stop: Stop, engine: Engine, ingest: Ingest, links: Links, open_watch: OpenWatch,
    resync: Callable[[str, bytes], None] | None = None,
) -> Callable[[], None]:
    """The `github-events` context: consume the inbox in the main store `engine` opens on a thread until `stop` is set; the store's owner disposes `engine`. The listener's
    container holds no producer token, so this runs apart from it, over the same store, with the `ingest` that holds it.

    The reconcile against GitHub and the retention purge (`starpulse github purge`) are the sweeper's, not a thread here. When the `github` producer may write
    the `pr-checks` machine it also publishes each check delivery and its head's rollup (`HeadChecks`), reading GitHub
    with `GITHUB_TOKEN` or `GH_TOKEN`, as the pull request adapter does.

    `resync`, when given, sees each delivery's event and body before its facts are read: the runtime root passes the runs
    context's `Resync`, which turns a Woodpecker `status` into a `runs:resync` (`github` sits below `runs` and `event_log`).

    Returns the context's reload, which has nothing to re-read."""
    if config.github is None:
        raise ValueError("no [github] table in the config")
    queue = SqlQueue(engine, CONSUMER, only=HANDLED)
    publishes_checks = any(CHECKS_MACHINE in p.machines for p in config.producers if p.name == "github")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    checks = HeadChecks(GitHubReader(connect(token))) if publishes_checks else None

    url = engine.url
    watch = open_watch(url.database) if url.get_backend_name() == "sqlite" and url.database else None

    def work() -> None:
        try:
            run(queue, ingest, links, stop, watch, checks, resync)
        finally:
            if watch is not None:
                watch.close()

    threading.Thread(target=work, name="github-events", daemon=True).start()
    return lambda: None
