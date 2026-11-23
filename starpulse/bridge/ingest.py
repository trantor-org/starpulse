"""The JetStream ingest: a producer publishes a CloudEvent to `ingest.<board>` and the server applies it.

A message is the HTTP ingest's request as it is: the CloudEvent as the body, `Authorization: Bearer <token>` and
`Content-Type` as headers. `apply` hands each to `CloudEventsIngest`, so the token check, the producer's machines and
actors and the append are the same ones the route makes. The stream keeps a message until `apply` settles it: an
accepted event is acknowledged, a refused one is logged and dropped (no producer is waiting to be told), and one the
event log did not take is delivered again.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from nats.errors import MaxPayloadError
from nats.js.api import ConsumerConfig

from starpulse.bridge.publisher import Publisher, Unavailable
from starpulse.event_log.wake import RETRY_DELAY, StopEvent

logger = logging.getLogger(__name__)

CONTENT_TYPE = "application/cloudevents+json"
DURABLE = "ingest"
Request = Callable[[str | None, str | None, bytes], tuple[int, dict[str, Any]]]


def stream(board: str) -> str:
    return f"starpulse-{board}-ingest"


def subject(board: str) -> str:
    return f"ingest.{board}"


class Producer:
    """Publishes CloudEvents to `board`'s ingest as the producer holding `token`; the connection opens on the first post."""

    def __init__(self, url: str, board: str, token: str) -> None:
        self._subject, self._headers = (
            subject(board),
            {"Authorization": f"Bearer {token}", "Content-Type": CONTENT_TYPE},
        )
        self._link = Publisher(url, stream(board), [self._subject], work_queue=True)

    def post(self, event: dict[str, Any]) -> int:
        """201 once the stream holds `event`, 413 when it is over the server's payload limit, 0 when the server is unreachable.

        A republish of one `source/id` is a no-op. Whether the server then applies the event is its own to settle."""
        try:
            self._link.publish(
                self._subject, json.dumps(event).encode(), f"{event['source']}/{event['id']}", self._headers
            )
        except MaxPayloadError:
            return 413
        except Unavailable:
            return 0
        return 201

    def close(self) -> None:
        self._link.close()


def apply(url: str, board: str, ingest: Request, stop: StopEvent) -> None:
    """Apply what producers publish to `board`'s ingest through `ingest` until `stop` is set, waiting for a server that is down."""
    link = Publisher(url, stream(board), [subject(board)], work_queue=True)

    async def receive(message: Any) -> None:
        headers = message.headers or {}
        try:
            status, body = await asyncio.get_running_loop().run_in_executor(
                None, ingest, headers.get("Authorization"), headers.get("Content-Type"), message.data
            )
        except Exception:  # the log's database is unreachable or locked; the delivery comes again
            logger.exception("ingest: applying a message failed, it is delivered again")
            return await message.nak(delay=RETRY_DELAY)
        if status == 503:
            return await message.nak(delay=RETRY_DELAY)
        if status != 201:
            logger.warning("ingest: dropped a message the server refused (%s): %s", status, body.get("error", ""))
        await message.ack()

    def subscribe(js: Any) -> Any:
        return js.subscribe(
            subject(board), durable=DURABLE, stream=stream(board), cb=receive, manual_ack=True, config=ConsumerConfig()
        )

    try:
        while not stop.is_set():
            try:
                link.run(subscribe)
                break
            except Unavailable as exc:  # the server is down; the subscription is made once it answers
                logger.warning("ingest: cannot subscribe, retrying: %s", exc)
                # adr-exempt: retry
                stop.wait(RETRY_DELAY)
        stop.wait()
    finally:
        link.close()
