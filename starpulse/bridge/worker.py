"""The bridge context: a thread of the `contexts` child that publishes the event log to the supervised NATS server and
keeps each session's consumer on the subjects of the task it holds.

It resumes from its own checkpoint (`bridge:nats`), saved after each acknowledged entry; a first start begins at the
newest entry. A down server only delays an entry: the publish is retried until it lands.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from typing import Any

from nats.errors import MaxPayloadError

from starpulse.bridge.consumers import Consumers
from starpulse.bridge.delivery import Delivery, JetStreamMailbox, Route
from starpulse.bridge.delivery import run as deliver
from starpulse.bridge.metrics import Published
from starpulse.bridge.publisher import Publisher, Unavailable
from starpulse.bridge.subjects import STREAMS, payload, subject_for
from starpulse.bridge.subscriber import Subscriber
from starpulse.bridge.subscriptions import Rules
from starpulse.event_log.event_log import Entry, EventLog, Tail
from starpulse.event_log.wake import RETRY_DELAY, StopEvent

logger = logging.getLogger(__name__)

CHECKPOINT = "bridge:nats"


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
            stop.wait(RETRY_DELAY)
    return False, None


def run(log: EventLog, publisher: Publisher, board: str, subscriber: Subscriber, stop: StopEvent) -> None:
    """Publish and subscribe until `stop` is set."""

    published = Published(log)

    def handle(entry: Entry) -> None:
        if subject := subject_for(board, entry):
            try:
                publisher.publish(subject, payload(entry), entry.event_id)
            except MaxPayloadError:  # no retry can land it; the entry stays in the event log
                logger.error("bridge: entry %s for %s exceeds the server's payload limit and is not published", entry.id, subject)
            else:
                published.count(subject)
        subscriber.handle(entry)
        log.checkpoints.save(CHECKPOINT, entry.id)

    try:
        started, position = _await_start_position(log, stop)
        if started:
            Tail(log, "bridge", after=position, streams=STREAMS).run(handle, stop, transient=(Unavailable,))
    finally:
        publisher.close()


def _deliver(delivery: Delivery, link: Publisher, stop: StopEvent) -> None:
    try:
        deliver(delivery, stop)
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
) -> Callable[[], None]:
    """Start the bridge over `log` for `board`, ending when `stop` is set; `feed()` is the board's read side. Return its reload.

    `route` finds how to reach a session's consumer: with it, the events waiting on a consumer it knows are delivered
    (`bridge.delivery`).
    """
    stream = f"starpulse-{board}"
    url = f"nats://127.0.0.1:{port}"
    publisher = Publisher(url, stream, f"starpulse.{board}.>")
    subscriber = Subscriber(board, rules, Consumers(publisher, stream), feed)
    threading.Thread(target=run, args=(log, publisher, board, subscriber, stop), name="bridge", daemon=True).start()
    if route:
        link = Publisher(url, stream, f"starpulse.{board}.>")
        delivery = Delivery(JetStreamMailbox(link, stream), route)
        threading.Thread(target=_deliver, args=(delivery, link, stop), name="bridge-delivery", daemon=True).start()
    return lambda: logger.info("reload: the bridge reads [bridge] at start; restart serve to apply a change")
