"""The bridge context: a thread of the `contexts` child that publishes the event log to the supervised NATS server and
keeps each session's consumer on the subjects of the task it holds, applying `subscribe` and `unsubscribe` too
(`bridge.requests`).

It resumes from its own checkpoint (`bridge:nats`), saved once per batch of acknowledged entries: a write per entry
queued behind the log's other writers and held the tail minutes behind under load. A crash replays at most one batch,
which the stream's message ids and the idempotent subscriber absorb. A first start begins at the newest entry. A down server only delays an entry: the publish is retried until it lands.
"""

import logging
import threading
from collections.abc import Callable, Collection, Mapping
from typing import Any

from nats.errors import MaxPayloadError
from nats.js.errors import BadRequestError

from starpulse.bridge import ingest
from starpulse.bridge.consumers import Consumers
from starpulse.bridge.delivery import Delivery, JetStreamMailbox, Route
from starpulse.bridge.metrics import Published
from starpulse.bridge.publisher import Publisher, Unavailable
from starpulse.bridge.reach import Reach
from starpulse.bridge.requests import serve
from starpulse.bridge.subjects import CHECKPOINT, STREAMS, payload, stream_subjects, subject_for, wake_subject
from starpulse.bridge.subscriber import Subscriber
from starpulse.bridge.subscriptions import Rules
from starpulse.event_log.event_log import Entry, EventLog, Tail
from starpulse.event_log.follower_lag import DELIVERY, Behind
from starpulse.event_log.wake import RETRY_DELAY, StopEvent

logger = logging.getLogger(__name__)


def _start_position(log: EventLog) -> int | None:
    """The checkpoint, else the newest bridged entry, saved so a restart before the next entry does not skip one."""
    position, _ = log.checkpoints.load(CHECKPOINT)
    if position is None:
        heads = [head for head in map(log.last, STREAMS) if head is not None]
        position = max(heads, default=None)
        if position is not None:
            log.checkpoints.save(CHECKPOINT, position)
    return position


def _await_start_position(log: EventLog, stop: StopEvent) -> tuple[bool, int | None]:
    """Whether a start position was read before `stop`, and it: a failed read is logged and retried."""
    while not stop.is_set():
        try:
            return True, _start_position(log)
        except Exception as exc:  # the log's database is unreachable or locked; the next read retries
            logger.warning("bridge: cannot read its start position, retrying: %s", exc)
            # adr-exempt: retry
            stop.wait(RETRY_DELAY)
    return False, None


def _reconcile(subscriber: Subscriber, stop: StopEvent) -> None:
    while not stop.is_set():
        try:
            return subscriber.reconcile()
        except Unavailable as exc:  # the server is down; the subscriptions are reconciled before the tail starts
            logger.warning("bridge: cannot reconcile the sessions' subscriptions, retrying: %s", exc)
            # adr-exempt: retry
            stop.wait(RETRY_DELAY)


def run(
    log: EventLog,
    publisher: Publisher,
    board: str,
    subscriber: Subscriber,
    stop: StopEvent,
    woke: Callable[[], None] = lambda: None,
) -> None:
    """Publish and subscribe until `stop` is set; `woke` runs after each entry, when a session's consumer may have news."""

    published = Published(log)
    handled = 0

    def handle(entry: Entry) -> None:
        if subject := subject_for(board, entry):
            try:
                publisher.publish(subject, payload(entry), entry.event_id)
            except MaxPayloadError:  # no retry can land it; the entry stays in the event log
                logger.error(
                    "bridge: entry %s for %s exceeds the server's payload limit and is not published", entry.id, subject
                )
            else:
                published.count(subject)
        try:
            subscriber.handle(entry)
        except BadRequestError as exc:  # the server refuses this subscription for good; retrying only stalls the tail
            logger.error("bridge: entry %s subscription is refused and skipped: %s", entry.id, exc)
        woke()
        nonlocal handled
        handled = entry.id

    def keep() -> None:
        published.keep()
        if handled:
            try:
                log.checkpoints.save(CHECKPOINT, handled)
            except Exception:  # noqa: BLE001 - a lost write only widens the replay; `handled` keeps, so the next batch saves past it
                logger.warning("bridge: the checkpoint was not saved at entry %s, the next batch retries", handled, exc_info=True)

    try:
        started, position = _await_start_position(log, stop)
        if started:
            _reconcile(subscriber, stop)
            Tail(log, "bridge", after=position, streams=STREAMS).run(
                handle, stop, transient=(Unavailable,), after_batch=keep
            )
    finally:
        publisher.close()


def _deliver(delivery: Delivery, link: Publisher, stop: StopEvent, registered: Callable[[], None]) -> None:
    try:
        registered()
        delivery.run(stop)
    finally:
        link.close()


def start(
    port: int,
    board: str,
    rules: Mapping[str, Rules],
    log: EventLog,
    feed: Callable[[], Any],
    stop: StopEvent,
    route: Route | None = None,
    settle: Callable[[Collection[str]], None] | None = None,
    reach: Mapping[str, Reach] | None = None,
    registered: Callable[[], None] = lambda: None,
    events: ingest.Request | None = None,
    running: Callable[[str], bool] | None = None,
) -> Callable[[], None]:
    """Start the bridge over `log` for `board`, ending when `stop` is set; `feed()` is the board's read side. Return its reload.

    `route` finds how to reach a session's consumer: with it, the events waiting on a consumer it knows are delivered
    (`bridge.delivery`); `running` says whether a consumer's session runs, so a routeless one that does leaves delivery behind. `reach` is each incident type's reach (`bridge.reach`). `settle` runs after each lane move and `reconcile`. `registered` runs when the delivery starts and each time a session registers. `events` applies what producers publish to the
    board's ingest (`bridge.ingest`); without it none is applied.
    """
    stream = f"starpulse-{board}"
    url = f"nats://127.0.0.1:{port}"
    publisher = Publisher(url, stream, stream_subjects(board))
    subscriber = Subscriber(board, rules, Consumers(publisher, stream), feed, settle, reach)
    delivery: Delivery | None = None
    if route:
        link = Publisher(url, stream, stream_subjects(board))
        delivery = Delivery(JetStreamMailbox(link, stream), route, behind=Behind(log, DELIVERY), **({"running": running} if running else {}))
        link.listen(
            wake_subject(board), lambda: (registered(), delivery.wake())
        )  # `starpulse subscribe` signals it once a session's route is registered
        threading.Thread(
            target=_deliver, args=(delivery, link, stop, registered), name="bridge-delivery", daemon=True
        ).start()
    wake = delivery.wake if delivery else lambda: None
    threading.Thread(
        target=run, args=(log, publisher, board, subscriber, stop, wake), name="bridge", daemon=True
    ).start()
    threading.Thread(target=serve, args=(url, board, subscriber, stop), name="bridge-requests", daemon=True).start()
    if events:
        threading.Thread(
            target=ingest.apply, args=(url, board, events, stop), name="bridge-ingest", daemon=True
        ).start()
    return lambda: logger.info("reload: the bridge reads [bridge] at start; restart serve to apply a change")
