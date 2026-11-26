"""Delivery: what the bridge does with the events waiting on a session's consumer.

A pass lists the consumers with messages waiting, and for each one the `Route` knows a way to reach (the runtime builds
it from the sessions' registrations) fetches a batch and hands it over. The batch is acknowledged only when the handler
took it; otherwise the server redelivers it after its ack wait, so a one-shot deadline at the consumer's ack wait runs
the next pass. A consumer with no route is not touched and its events stay on it until a route is registered.

A pass runs when `wake` is called (the bridge published an entry, or a session registered its route), when a
deadline fires, and again after each acknowledged batch, which may have left events waiting.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from starpulse.bridge.consumers import all_consumers
from starpulse.bridge.publisher import Publisher, Unavailable
from starpulse.bridge.subjects import INCIDENT
from starpulse.event_log.deadlines import Deadlines
from starpulse.event_log.follower_lag import Behind
from starpulse.event_log.wake import RETRY_DELAY, StopEvent

logger = logging.getLogger(__name__)

_BATCH = 100
#: A holder's resume, a move, feedback and an uncited PR's verdict are one-time wakes: the consumer's `LAST_PER_SUBJECT` start replays the
#: last of each, however old, and a move before the claim is history to the session it then wakes in the lane it left.
ONE_TIME = (".holder_resume", ".moved", ".feedback", ".uncited_checks")
_FETCH_TIMEOUT_S = 0.2


def _one_time(subject: str) -> bool:
    """A holder's resume, a move and an incident, which a session subscribing after it was published has nothing to do with."""
    return subject.endswith(ONE_TIME) or subject.startswith(INCIDENT)


@dataclass(frozen=True)
class Event:
    subject: str
    body: bytes


@dataclass(frozen=True)
class Fetched:
    events: list[Event]
    ack: Callable[[], None]


class Mailbox(Protocol):
    def waiting(self) -> dict[str, float]:
        """The consumers with messages waiting, each with the ack wait the server redelivers an unacknowledged one after."""

    def fetch(self, name: str) -> Fetched: ...


Handler = Callable[[list[Event]], bool]
Route = Callable[[str], Handler | None]


class Delivery:
    def __init__(
        self,
        mailbox: Mailbox,
        route: Route,
        *,
        clock: Callable[[], float] = time.time,
        behind: Behind | None = None,
        running: Callable[[str], bool] = lambda _name: False,
    ) -> None:
        self._mailbox, self._route, self._clock, self._behind = mailbox, route, clock, behind
        self._running = running
        self._unrouted: set[str] = set()
        self._woken = threading.Event()
        self._deadlines = Deadlines(lambda _name: self.wake(), clock=clock)

    def wake(self) -> None:
        self._woken.set()

    def once(self) -> None:
        """One pass. A consumer with events waiting and no route whose session `running` says runs is behind, on every pass
        until it registers: its holder is live and will never be told."""
        stuck = False
        for name, ack_wait in self._mailbox.waiting().items():
            handler = self._route(name)
            if handler is None:
                if name not in self._unrouted:
                    self._unrouted.add(name)
                    logger.warning("delivery: consumer %s has events waiting and no session route", name)
                stuck = stuck or self._running(name)
                continue
            self._unrouted.discard(name)
            try:
                fetched = self._mailbox.fetch(name)
                if fetched.events and handler(fetched.events):
                    fetched.ack()
                    self.wake()
                    continue
            except Unavailable:
                raise
            except Exception:  # noqa: BLE001 — one session's failure never stops delivery to the rest
                logger.exception("delivery: session %s failed", name)
            stuck = True
            self._deadlines.arm(name, self._clock() + ack_wait)
        if self._behind and stuck:
            self._behind.since(self._clock())
        elif self._behind:
            self._behind.caught_up()

    def run(self, stop: StopEvent) -> None:
        """Pass over the consumers each time woken, and once at start, until `stop` is set; a pass that failed (the
        server did not answer) is tried again after `RETRY_DELAY`."""
        stop.listen(self._woken.set)
        self._deadlines.start(stop, thread_name="bridge-delivery-deadlines")
        self._woken.set()
        while True:
            self._woken.wait()
            self._woken.clear()  # a wake during the pass below runs the next pass
            if stop.is_set():
                return
            try:
                self.once()
            except Unavailable as exc:
                logger.warning("delivery: the NATS server did not answer: %s", exc)
                if self._behind:
                    self._behind.since(self._clock())
            except Exception:  # noqa: BLE001 — a failed pass never ends delivery
                logger.exception("delivery: a pass failed")
            else:
                continue
            # adr-exempt: retry
            stop.wait(RETRY_DELAY)
            self._woken.set()


class JetStreamMailbox:
    """The consumers of one stream over a `Publisher`'s connection."""

    def __init__(self, link: Publisher, stream: str) -> None:
        self._link, self._stream = link, stream

    def waiting(self) -> dict[str, float]:
        async def read(js):  # noqa: ANN001, ANN202
            return await all_consumers(js, self._stream)

        return {
            info.name: info.config.ack_wait for info in self._link.run(read) if info.num_pending or info.num_ack_pending
        }

    def fetch(self, name: str) -> Fetched:
        held = []

        async def read(js):  # noqa: ANN001, ANN202
            pull = await js.pull_subscribe_bind(name, self._stream)
            try:
                batch = await pull.fetch(_BATCH, timeout=_FETCH_TIMEOUT_S)
                once = any(_one_time(message.subject) for message in batch)
                created = (await js.consumer_info(self._stream, name)).created if once else None
                for message in batch:
                    if created and _one_time(message.subject) and message.metadata.timestamp < created:
                        await message.ack()
                    else:
                        held.append(message)
            except TimeoutError:  # nats-py raises the builtin, not its own, when the reply lands after the window
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
