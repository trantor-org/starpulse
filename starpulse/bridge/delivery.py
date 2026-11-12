"""Delivery: what the bridge does with the events waiting on a session's consumer.

A pass lists the consumers with messages waiting, and for each one the `Route` knows a way to reach (the runtime builds
it from the sessions' registrations) fetches a batch and hands it over. The batch is acknowledged only when the handler
took it; otherwise the server redelivers it after its ack wait, so a session that was unreachable, or still starting, is
told when it can be. A consumer with no route is not touched and its events stay on it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from nats.errors import TimeoutError as FetchTimeout

from starpulse.bridge.publisher import Publisher, Unavailable
from starpulse.event_log.wake import StopEvent

logger = logging.getLogger(__name__)

INTERVAL_S = 1.0
_BATCH = 100
_FETCH_TIMEOUT_S = 0.2


@dataclass(frozen=True)
class Event:
    subject: str
    body: bytes


@dataclass(frozen=True)
class Fetched:
    events: list[Event]
    ack: Callable[[], None]


class Mailbox(Protocol):
    def waiting(self) -> list[str]: ...

    def fetch(self, name: str) -> Fetched: ...


Handler = Callable[[list[Event]], bool]
Route = Callable[[str], Handler | None]


class Delivery:
    def __init__(self, mailbox: Mailbox, route: Route) -> None:
        self._mailbox, self._route = mailbox, route

    def once(self) -> None:
        for name in self._mailbox.waiting():
            handler = self._route(name)
            if handler is None:
                continue
            try:
                fetched = self._mailbox.fetch(name)
                if fetched.events and handler(fetched.events):
                    fetched.ack()
            except Unavailable:
                raise
            except Exception:  # noqa: BLE001 — one session's failure never stops delivery to the rest
                logger.exception("delivery: session %s failed", name)


class JetStreamMailbox:
    """The consumers of one stream over a `Publisher`'s connection."""

    def __init__(self, link: Publisher, stream: str) -> None:
        self._link, self._stream = link, stream

    def waiting(self) -> list[str]:
        async def read(js):  # noqa: ANN001, ANN202
            return await js.consumers_info(self._stream)

        return [info.name for info in self._link.run(read) if info.num_pending or info.num_ack_pending]

    def fetch(self, name: str) -> Fetched:
        held = []

        async def read(js):  # noqa: ANN001, ANN202
            pull = await js.pull_subscribe_bind(name, self._stream)
            try:
                held.extend(await pull.fetch(_BATCH, timeout=_FETCH_TIMEOUT_S))
            except FetchTimeout:
                pass
            finally:
                await pull.unsubscribe()

        self._link.run(read)

        async def acknowledge(js):  # noqa: ANN001, ANN202, ARG001
            for message in held:
                await message.ack()

        return Fetched(
            [Event(message.subject, message.data) for message in held], lambda: self._link.run(acknowledge)
        )


def run(delivery: Delivery, stop: StopEvent) -> None:
    """Pass over the consumers every `INTERVAL_S` until `stop` is set; a server that does not answer is tried again."""
    while not stop.wait(INTERVAL_S):
        try:
            delivery.once()
        except Unavailable as exc:
            logger.warning("delivery: the NATS server did not answer: %s", exc)
        except Exception:  # noqa: BLE001 — a failed pass never ends delivery
            logger.exception("delivery: a pass failed")
