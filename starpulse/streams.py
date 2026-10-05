"""Redis Streams, both halves of the at-least-once contract StarPulse reads and writes.

* `StreamProducer` emits fail-open: it mints the `event_id` every consumer keys on, trims with an approximate
  `maxlen`, and never raises, so emitting an event never fails the work that caused it. A stream is therefore not
  durable storage: an outage at emit time drops the event.
* `StreamConsumer` consumes through a consumer group: it retries its own pending entries before reading new ones,
  reclaims entries stranded by a dead consumer with `XAUTOCLAIM`, and dead-letters a payload that keeps failing
  so it cannot wedge the group. An entry is acked only after its handler returns, so handlers must be idempotent.

A client reaches Redis at `<prefix>_REDIS_HOST` and `<prefix>_REDIS_PORT` with the shared `REDIS_PASSWORD` (or the
file `REDIS_PASSWORD_FILE` names) as the ACL user `REDIS_USERNAME` (or the default user), over TLS when the shared
`REDIS_SSL` is `1`; `starpulse.runtime` sets those from `REDIS_URL`, whose `rediss://` scheme turns TLS on.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self, cast
from urllib.parse import unquote, urlsplit

import redis
import redis.exceptions

logger = logging.getLogger(__name__)


def _password() -> str | None:
    """The shared `REDIS_PASSWORD`, or the contents of the file `REDIS_PASSWORD_FILE` names."""
    if value := os.environ.get("REDIS_PASSWORD"):  # noqa: AGT101
        return value
    if path := os.environ.get("REDIS_PASSWORD_FILE"):  # noqa: AGT101
        return Path(path).read_text().strip()
    return None


def redis_endpoint_from_env(prefix: str) -> dict[str, Any]:
    """The `redis_host`/`redis_port`/`redis_username`/`redis_password`/`redis_ssl` keywords both stream classes take,
    from `<prefix>_REDIS_*`."""
    return {
        "redis_host": os.environ.get(f"{prefix}_REDIS_HOST", "127.0.0.1"),  # noqa: AGT101
        "redis_port": int(os.environ.get(f"{prefix}_REDIS_PORT", "6379")),  # noqa: AGT101
        "redis_username": os.environ.get("REDIS_USERNAME"),  # noqa: AGT101
        "redis_password": _password(),
        "redis_ssl": os.environ.get("REDIS_SSL") == "1",  # noqa: AGT101
    }


def endpoint_from_url(url: str, password: str | None = None, username: str | None = None) -> dict[str, Any]:
    """The same keywords from a `redis://` or `rediss://` (TLS) URL; the URL's own percent-decoded user and password win
    over `username` and `password`.

    A port that is not a number raises `ValueError`."""
    parts = urlsplit(url)
    return {
        "redis_host": parts.hostname or "127.0.0.1",
        "redis_port": parts.port or 6379,
        "redis_username": unquote(parts.username) if parts.username else username,
        "redis_password": unquote(parts.password) if parts.password else password,
        "redis_ssl": parts.scheme == "rediss",
    }


class StreamConsumer:
    """Consume a Redis Stream through a consumer group, with retry and dead-lettering.

    `handler(entry_id, fields)` returning acks the entry; raising leaves it pending for redelivery until
    `max_delivery_attempts` dead-letters it (acked unprocessed). The count is Redis' own delivery counter, floored by
    the in-process `delivery_attempts`, so it survives a restart. `transient` exception types mean the sink is down,
    not the entry bad: they re-raise without counting. `group_start_id` is where a newly created group begins: `"0"`
    replays everything the stream retains, `"$"` takes only new entries; an existing group keeps its position.
    """

    def __init__(
        self,
        *,
        stream: str,
        group: str,
        consumer: str,
        handler: Callable[[str, dict], None],
        redis_host: str = "127.0.0.1",
        redis_port: int = 6379,
        redis_username: str | None = None,
        redis_password: str | None = None,
        redis_ssl: bool = False,
        read_batch: int = 50,
        read_block_ms: int = 5000,
        claim_idle_ms: int = 60000,
        max_delivery_attempts: int = 5,
        reconnect_delay: float = 5.0,
        group_start_id: str = "0",
        delivery_attempts: dict[str, int] | None = None,
        transient: tuple[type[BaseException], ...] = (),
    ) -> None:
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.handler = handler
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_username = redis_username
        self.redis_password = redis_password
        self.redis_ssl = redis_ssl
        self.read_batch = read_batch
        self.read_block_ms = read_block_ms
        self.claim_idle_ms = claim_idle_ms
        self.max_delivery_attempts = max_delivery_attempts
        self.reconnect_delay = reconnect_delay
        self.group_start_id = group_start_id
        self.delivery_attempts = delivery_attempts if delivery_attempts is not None else {}
        self.transient = transient

    @classmethod
    def from_env(cls, prefix: str, **kwargs: Any) -> Self:
        """A consumer on the Redis `<prefix>_REDIS_*` names; `kwargs` are the stream, group, consumer and handler."""
        return cls(**redis_endpoint_from_env(prefix), **kwargs)

    def redis_delivery_count(self, client, entry_id: str) -> int:
        """Redis' own delivery count for `entry_id`, else 0; any Redis error falls back to the in-memory count."""
        try:
            pending = client.xpending_range(self.stream, self.group, min=entry_id, max=entry_id, count=1)
        except Exception:  # fail open to the in-memory counter
            return 0
        for item in pending or []:
            try:
                raw_count = item.get("times_delivered", 0)  # pragma: no mutate - an absent count normalizes to zero
                return int(raw_count)
            except AttributeError, TypeError, ValueError:
                return 0
        return 0

    def process_message(self, client, entry_id: str, fields: dict) -> None:
        """Run the handler for one entry and ack it; a failure below the attempt limit re-raises, leaving it pending."""
        try:
            self.handler(entry_id, fields)
        except self.transient:
            raise
        except Exception:
            local_attempts = self.delivery_attempts.get(entry_id, 0) + 1
            self.delivery_attempts[entry_id] = local_attempts
            attempts = max(local_attempts, self.redis_delivery_count(client, entry_id))
            if attempts >= self.max_delivery_attempts:
                logger.warning(
                    "%s: entry %s exceeded %d delivery attempts; dead-lettering (acking without processing)",
                    self.consumer,
                    entry_id,
                    self.max_delivery_attempts,
                )
                client.xack(self.stream, self.group, entry_id)
                self.delivery_attempts.pop(
                    entry_id, None
                )  # pragma: no mutate - the entry was assigned immediately above
                return
            raise
        self.delivery_attempts.pop(entry_id, None)
        client.xack(self.stream, self.group, entry_id)

    def consume_once(self, client) -> None:
        """Read and process one batch: own pending entries one at a time, then stranded ones, then new ones.

        A pending re-read charges a delivery to every entry it returns, so they are re-read singly and a failing head
        stops the pass before the entries behind it are charged. Failures re-raise so the caller reconnects.
        """
        try:
            client.xgroup_create(self.stream, self.group, id=self.group_start_id, mkstream=True)
        except redis.exceptions.ResponseError:
            pass  # group already exists
        for _ in range(self.read_batch):
            pending = client.xreadgroup(self.group, self.consumer, {self.stream: "0"}, count=1)
            items = [item for _stream, entries in pending for item in entries]
            if not items:
                break
            for entry_id, fields in items:
                self.process_message(client, entry_id, fields)
        _next_id, claimed, _deleted = client.xautoclaim(
            self.stream,
            self.group,
            self.consumer,
            min_idle_time=self.claim_idle_ms,
            start_id="0-0",
            count=self.read_batch,
        )
        for entry_id, fields in claimed:
            self.process_message(client, entry_id, fields)
        entries = client.xreadgroup(
            self.group,
            self.consumer,
            {self.stream: ">"},
            count=self.read_batch,
            block=self.read_block_ms,
        )
        if not entries:
            return
        for _stream, items in entries:
            for entry_id, fields in items:
                self.process_message(client, entry_id, fields)

    # Margin between the blocking read and the socket deadline that bounds it.
    SOCKET_TIMEOUT_MARGIN_S = 5

    def connect(self):
        """A decoded-response client whose socket deadline outlasts the blocking read, so an idle stream never times out."""
        return redis.Redis(
            host=self.redis_host,
            port=self.redis_port,
            username=self.redis_username,
            password=self.redis_password,
            ssl=self.redis_ssl,
            socket_connect_timeout=5,
            socket_timeout=self.read_block_ms / 1000 + self.SOCKET_TIMEOUT_MARGIN_S,
            decode_responses=True,
        )

    def run_forever(self) -> None:
        """Consume until killed, reconnecting on any Redis-level error."""
        while True:
            try:
                client = self.connect()
                logger.info("%s consuming stream %s (group %s)", self.consumer, self.stream, self.group)
                while True:
                    self.consume_once(client)
            except Exception as e:  # reconnect loop
                logger.warning("%s: Redis error, reconnecting in %ss: %s", self.consumer, self.reconnect_delay, e)
                time.sleep(self.reconnect_delay)


class StreamProducer:
    """Emit events to a Redis Stream, fail-open, with a minted `event_id`.

    `client_factory` is injectable so a caller can share a connection (or a fake, in tests); without it the producer
    owns a lazily created client and rebuilds it on the next emit after a failure. A value that is not a string is
    JSON-encoded and `None` is dropped, since Redis Streams store flat string maps.
    """

    def __init__(
        self,
        *,
        stream: str,
        maxlen: int = 10000,
        redis_host: str = "127.0.0.1",
        redis_port: int = 6379,
        redis_username: str | None = None,
        redis_password: str | None = None,
        redis_ssl: bool = False,
        client_factory: Any = None,
    ) -> None:
        self.stream = stream
        self.maxlen = maxlen
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_username = redis_username
        self.redis_password = redis_password
        self.redis_ssl = redis_ssl
        self._client_factory = client_factory
        self._client = None

    @classmethod
    def from_env(cls, prefix: str, **kwargs: Any) -> Self:
        """A producer on the Redis `<prefix>_REDIS_*` names; `kwargs` carry the stream."""
        return cls(**redis_endpoint_from_env(prefix), **kwargs)

    def connect(self):
        """A client, built on first use or after a failure."""
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            self._client = self._client_factory()
        else:
            self._client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                username=self.redis_username,
                password=self.redis_password,
                ssl=self.redis_ssl,
                socket_connect_timeout=5,
                socket_timeout=5,
                decode_responses=True,
            )
        return self._client

    @staticmethod
    def _encode(fields: dict[str, Any]) -> dict[str, str]:
        return {
            key: value if isinstance(value, str) else json.dumps(value)
            for key, value in fields.items()
            if value is not None
        }

    def emit(self, fields: dict[str, Any], *, event_id: str | None = None) -> str | None:
        """XADD one event and return its entry id, or None when the emit failed; never raises.

        `event_id` is minted unless the caller supplies one, as a replaying caller does. Encoding sits inside the
        `try`: a value `json.dumps` refuses must fail open like an outage.
        """
        try:
            payload = self._encode(fields)
            payload["event_id"] = event_id or str(uuid.uuid4())
            redis_payload = cast("Any", payload)  # pragma: no mutate - type-only cast is erased at runtime
            entry_id = self.connect().xadd(self.stream, redis_payload, maxlen=self.maxlen, approximate=True)
            return cast("str", entry_id)  # pragma: no mutate - type-only cast is erased at runtime
        except Exception as exc:  # fail open, see module docstring
            logger.warning("StreamProducer: emit to %s failed (event dropped): %s", self.stream, exc)
            self._client = None
            return None
