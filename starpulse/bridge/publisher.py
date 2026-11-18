"""A synchronous JetStream client over `nats-py`, whose connection lives on a loop thread of its own.

Nothing connects until the first call, so the bridge starts before the server is up; a call that cannot reach the
server or its stream raises `Unavailable` and the next one reconnects and declares the stream again, which also recovers
a deleted store. It publishes, and `run` hands any other JetStream operation (the consumers) the same connection.
"""

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import nats
from nats.errors import Error as NatsError
from nats.errors import MaxPayloadError
from nats.js.api import StorageType, StreamConfig
from nats.js.errors import BadRequestError

#: Messages kept per subject: the newest events of a task or pull request, which is what a late subscriber starts from.
PER_SUBJECT = 100
_TIMEOUT_S = 5.0
T = TypeVar("T")


class Unavailable(Exception):
    """The server or the stream did not take the message; the entry is not lost, the bridge retries it."""


def _calling(callback: Callable[[], None]) -> Callable[[Any], Awaitable[None]]:
    async def receive(_message: Any) -> None:
        callback()

    return receive


class Publisher:
    def __init__(self, url: str, stream: str, subjects: list[str]) -> None:
        self._url = url
        self._config = StreamConfig(
            name=stream, subjects=subjects, storage=StorageType.FILE, max_msgs_per_subject=PER_SUBJECT
        )
        self._loop = asyncio.new_event_loop()
        self._client: Any = None
        self._js: Any = None
        self._one = asyncio.Lock()
        self._listening: list[tuple[str, Callable[[], None]]] = []
        threading.Thread(target=self._loop.run_forever, name="bridge-nats", daemon=True).start()

    def publish(self, subject: str, body: bytes, msg_id: str) -> None:
        """Publish `body` and wait for the stream's ack; `msg_id` makes a republish within the duplicate window a no-op."""
        self.run(lambda js: js.publish(subject, body, headers={"Nats-Msg-Id": msg_id}, timeout=_TIMEOUT_S))

    def listen(self, subject: str, callback: Callable[[], None]) -> None:
        """Call `callback` for each message on the core `subject` once connected; set before the first call to `run`."""
        self._listening.append((subject, callback))

    def signal(self, subject: str) -> None:
        """Publish an empty core message on `subject` (outside any stream) to whoever listens."""

        async def send(_js: Any) -> None:
            await self._client.publish(subject)
            await self._client.flush(timeout=_TIMEOUT_S)

        self.run(send)

    def run(self, operation: Callable[[Any], Awaitable[T]]) -> T:
        """Run `operation(jetstream)` on the loop thread once the stream exists, and return what it returns.

        A `MaxPayloadError` is permanent, not an outage: it reaches the caller as it is, and the connection stays.
        """
        future = asyncio.run_coroutine_threadsafe(self._run(operation), self._loop)
        try:
            return future.result(timeout=_TIMEOUT_S * 3)
        except MaxPayloadError:
            raise
        except (NatsError, OSError, TimeoutError) as exc:
            future.cancel()
            raise Unavailable(f"{type(exc).__name__}: {exc}") from exc

    async def _run(self, operation: Callable[[Any], Awaitable[T]]) -> T:
        async with self._one:  # the tail and the bridge's requests share the connection: one connects, one drops it
            try:
                if self._js is None:
                    self._client = await nats.connect(self._url, connect_timeout=_TIMEOUT_S, max_reconnect_attempts=-1)
                    self._js = self._client.jetstream()
                    for subject, callback in self._listening:
                        await self._client.subscribe(subject, cb=_calling(callback))
                await self._declare()
                return await operation(self._js)
            except MaxPayloadError:
                raise
            except BaseException:
                await self._drop()
                raise

    async def _declare(self) -> None:
        """Create the stream, which also recreates a deleted store; a stream an older release made for other subjects is updated."""
        try:
            await self._js.add_stream(self._config)
        except BadRequestError:
            await self._js.update_stream(self._config)

    async def _drop(self) -> None:
        client, self._client, self._js = self._client, None, None
        if client is not None:
            try:
                await client.close()
            except NatsError, OSError:
                pass

    def close(self) -> None:
        asyncio.run_coroutine_threadsafe(self._drop(), self._loop).result(timeout=_TIMEOUT_S)
        self._loop.call_soon_threadsafe(self._loop.stop)
