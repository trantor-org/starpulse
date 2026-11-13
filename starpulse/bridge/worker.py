"""The bridge context: a thread of the `contexts` child that publishes the event log to the supervised NATS server and
keeps each session's consumer on the subjects of the task it holds.

It reads `board:lanes` and `machine:events` in log order from its own checkpoint (`bridge:nats`), saved after each entry
the server acknowledged, so a restart resumes at the first entry not published; a crash between the ack and the save
republishes one entry, which the stream drops by its `Nats-Msg-Id` (the entry's event id), and the subscriber reads the
entry again to the same result. A first start has no
checkpoint and starts at the newest entry: a subscriber is given the latest state, never the history. The server being
down, or its store deleted, only delays the entry: the cursor goes back and the publish is retried until it lands.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from typing import Any

from starpulse.bridge.consumers import Consumers
from starpulse.bridge.delivery import Delivery, JetStreamMailbox, Route
from starpulse.bridge.delivery import run as deliver
from starpulse.bridge.metrics import Published
from starpulse.bridge.publisher import Publisher, Unavailable
from starpulse.bridge.subjects import STREAMS, payload, subject_for
from starpulse.bridge.subscriber import Subscriber
from starpulse.bridge.subscriptions import Rules
from starpulse.event_log.event_log import Entry, EventLog, Tail
from starpulse.event_log.wake import StopEvent

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


def run(log: EventLog, publisher: Publisher, board: str, subscriber: Subscriber, stop: StopEvent) -> None:
    """Publish and subscribe until `stop` is set."""

    published = Published(log)

    def handle(entry: Entry) -> None:
        if subject := subject_for(board, entry):
            publisher.publish(subject, payload(entry), entry.event_id)
            published.count(subject)
        subscriber.handle(entry)
        log.checkpoints.save(CHECKPOINT, entry.id)

    tail = Tail(log, "bridge", after=_start_position(log), streams=STREAMS)
    try:
        tail.run(handle, stop, transient=(Unavailable,))
    finally:
        publisher.close()


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
        mailbox = JetStreamMailbox(Publisher(url, stream, f"starpulse.{board}.>"), stream)
        delivery = Delivery(mailbox, route)
        threading.Thread(target=deliver, args=(delivery, stop), name="bridge-delivery", daemon=True).start()
    return lambda: logger.info("reload: the bridge reads [bridge] at start; restart serve to apply a change")
