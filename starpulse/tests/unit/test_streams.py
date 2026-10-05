"""The Redis client each stream end builds, and the delivery count a consumer reads back from Redis."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from starpulse.streams import StreamConsumer, StreamProducer, endpoint_from_url, redis_endpoint_from_env


def _consumer(handler: Callable[[str, dict], None] = lambda entry_id, fields: None, **over: Any) -> StreamConsumer:
    return StreamConsumer(stream="s", group="g", consumer="c", handler=handler, **over)


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    class CapturedRedis:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("starpulse.streams.redis.Redis", CapturedRedis)
    return captured


def test_a_consumers_socket_deadline_outlasts_its_blocking_read(built: dict[str, Any]) -> None:
    _consumer(redis_host="redis", redis_port=6380, redis_password="secret", read_block_ms=2000).connect()

    assert built == {
        "host": "redis",
        "port": 6380,
        "username": None,
        "password": "secret",
        "ssl": False,
        "socket_connect_timeout": 5,
        "socket_timeout": 2 + StreamConsumer.SOCKET_TIMEOUT_MARGIN_S,
        "decode_responses": True,
    }


def test_a_producer_builds_one_decoded_client_on_its_endpoint(built: dict[str, Any]) -> None:
    producer = StreamProducer(stream="s", redis_host="redis", redis_port=6380, redis_password="secret")

    assert producer.connect() is producer.connect()
    assert built == {
        "host": "redis",
        "port": 6380,
        "username": None,
        "password": "secret",
        "ssl": False,
        "socket_connect_timeout": 5,
        "socket_timeout": 5,
        "decode_responses": True,
    }


class _Pending:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[tuple[Any, ...]] = []

    def xpending_range(self, stream: str, group: str, *, min: str, max: str, count: int) -> Any:
        self.calls.append((stream, group, min, max, count))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_the_delivery_count_is_redis_own_for_exactly_that_entry() -> None:
    client = _Pending([{"times_delivered": 4}])

    assert _consumer().redis_delivery_count(client, "1-0") == 4
    assert client.calls == [("s", "g", "1-0", "1-0", 1)]


class _Delivered:
    """Redis reporting `count` deliveries of entry 7-0 alone, and the entries acked."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.acked: list[tuple[str, str, str]] = []

    def xpending_range(self, stream: str, group: str, *, min: str, max: str, count: int) -> list[dict]:
        return [{"times_delivered": self.count}] if min == "7-0" else []

    def xack(self, stream: str, group: str, entry_id: str) -> None:
        self.acked.append((stream, group, entry_id))


def _failing(entry_id: str, fields: dict) -> None:
    raise ValueError("unplaceable")


def test_a_first_failure_redis_has_delivered_the_limit_times_is_dead_lettered() -> None:
    client = _Delivered(3)

    _consumer(handler=_failing, max_delivery_attempts=3).process_message(client, "7-0", {})

    assert client.acked == [("s", "g", "7-0")]


def test_a_failure_below_redis_delivery_limit_stays_pending() -> None:
    client = _Delivered(2)

    with pytest.raises(ValueError, match="unplaceable"):
        _consumer(handler=_failing, max_delivery_attempts=3).process_message(client, "7-0", {})
    assert client.acked == []


def test_an_entry_that_keeps_failing_is_dead_lettered_once_the_consumer_has_counted_the_limit() -> None:
    client = _Delivered(0)
    consumer = _consumer(handler=_failing, max_delivery_attempts=2)

    with pytest.raises(ValueError, match="unplaceable"):
        consumer.process_message(client, "7-0", {})
    consumer.process_message(client, "7-0", {})

    assert client.acked == [("s", "g", "7-0")]
    assert consumer.delivery_attempts == {}


def test_a_consumer_defaults_to_a_local_redis_and_its_own_attempt_count() -> None:
    consumer = _consumer()

    assert {
        key: value for key, value in vars(consumer).items() if key not in {"stream", "group", "consumer", "handler"}
    } == {
        "redis_host": "127.0.0.1",
        "redis_port": 6379,
        "redis_username": None,
        "redis_password": None,
        "redis_ssl": False,
        "read_batch": 50,
        "read_block_ms": 5000,
        "claim_idle_ms": 60000,
        "max_delivery_attempts": 5,
        "reconnect_delay": 5.0,
        "group_start_id": "0",
        "delivery_attempts": {},
        "transient": (),
    }


def test_a_consumer_keeps_the_attempt_count_and_reconnect_delay_it_is_given() -> None:
    attempts = {"1-0": 2}

    consumer = _consumer(reconnect_delay=0.25, delivery_attempts=attempts)

    assert consumer.delivery_attempts is attempts
    assert consumer.reconnect_delay == 0.25


def test_an_entry_handled_after_a_failure_forgets_its_attempts() -> None:
    calls: list[str] = []

    def flaky(entry_id: str, fields: dict) -> None:
        calls.append(entry_id)
        if len(calls) == 1:
            raise ValueError("unplaceable")

    client = _Delivered(0)
    consumer = _consumer(handler=flaky)

    with pytest.raises(ValueError, match="unplaceable"):
        consumer.process_message(client, "7-0", {})
    consumer.process_message(client, "7-0", {})

    assert consumer.delivery_attempts == {}
    assert client.acked == [("s", "g", "7-0")]


class _Stranded(_Delivered):
    """A stream with nothing pending or new, and one entry another consumer left idle."""

    def xgroup_create(self, *args: Any, **kwargs: Any) -> None:
        pass

    def xreadgroup(self, *args: Any, **kwargs: Any) -> list:
        return []

    def xautoclaim(self, *args: Any, **kwargs: Any) -> tuple[str, list, list]:
        return "0-0", [("5-0", {"task": "PROJ-1"})], []


def test_a_claimed_entry_is_handled_with_its_fields_and_acked() -> None:
    handled: list[tuple[str, dict]] = []
    client = _Stranded(0)

    _consumer(handler=lambda entry_id, fields: handled.append((entry_id, fields))).consume_once(client)

    assert handled == [("5-0", {"task": "PROJ-1"})]
    assert client.acked == [("s", "g", "5-0")]


class _OwnPending(_Stranded):
    """A stream holding one entry already delivered to this consumer, re-read one at a time."""

    def __init__(self) -> None:
        super().__init__(0)
        self.pending: list[tuple[str, dict]] = [("3-0", {"task": "PROJ-3"})]
        self.pending_counts: list[int] = []

    def xreadgroup(self, group: str, consumer: str, streams: dict, **kwargs: Any) -> list:
        if streams != {"s": "0"}:
            return []
        self.pending_counts.append(kwargs["count"])
        entries, self.pending = self.pending, []
        return [("s", entries)] if entries else []

    def xautoclaim(self, *args: Any, **kwargs: Any) -> tuple[str, list, list]:
        return "0-0", [], []


def test_an_own_pending_entry_is_re_read_singly_and_handled_by_its_id() -> None:
    handled: list[tuple[str, dict]] = []
    client = _OwnPending()

    _consumer(handler=lambda entry_id, fields: handled.append((entry_id, fields))).consume_once(client)

    assert handled == [("3-0", {"task": "PROJ-3"})]
    assert client.pending_counts == [1, 1]
    assert client.acked == [("s", "g", "3-0")]


class _Adding:
    def __init__(self, fail: bool) -> None:
        self.fail = fail
        self.added: list[tuple[str, dict, dict]] = []

    def xadd(self, stream: str, payload: dict, **kwargs: Any) -> str:
        if self.fail:
            raise ConnectionError("unavailable")
        self.added.append((stream, payload, kwargs))
        return "1-0"


def test_an_emit_trims_the_stream_approximately_and_reconnects_after_a_failure() -> None:
    clients = [_Adding(fail=True), _Adding(fail=False)]
    producer = StreamProducer(stream="s", maxlen=100, client_factory=lambda: clients.pop(0))

    assert producer.emit({"a": 1}, event_id="e1") is None
    assert producer.emit({"a": 1}, event_id="e1") == "1-0"

    assert not clients
    assert producer.connect().added == [("s", {"a": "1", "event_id": "e1"}, {"maxlen": 100, "approximate": True})]


def test_a_producer_defaults_to_a_local_redis_and_a_ten_thousand_entry_stream() -> None:
    producer = StreamProducer(stream="s")

    assert (producer.maxlen, producer.redis_host, producer.redis_port, producer.redis_password) == (
        10000,
        "127.0.0.1",
        6379,
        None,
    )


@pytest.fixture
def bare_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in (
        "X_REDIS_HOST",
        "X_REDIS_PORT",
        "REDIS_PASSWORD",
        "REDIS_PASSWORD_FILE",
        "REDIS_SSL",
        "REDIS_USERNAME",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_an_endpoint_with_nothing_set_is_a_local_redis_without_a_password(bare_env: pytest.MonkeyPatch) -> None:
    assert redis_endpoint_from_env("X") == {
        "redis_host": "127.0.0.1",
        "redis_port": 6379,
        "redis_username": None,
        "redis_password": None,
        "redis_ssl": False,
    }


def test_an_endpoint_reaches_redis_over_tls_when_redis_ssl_is_set(bare_env: pytest.MonkeyPatch) -> None:
    bare_env.setenv("REDIS_SSL", "1")

    assert redis_endpoint_from_env("X")["redis_ssl"] is True


def test_an_endpoint_names_its_acl_user_from_redis_username(bare_env: pytest.MonkeyPatch) -> None:
    bare_env.setenv("REDIS_USERNAME", "worker")

    assert redis_endpoint_from_env("X")["redis_username"] == "worker"


@pytest.mark.parametrize("build", [lambda **kw: StreamProducer(stream="s", **kw), _consumer])
def test_a_tls_endpoint_with_a_user_builds_a_tls_client_for_that_user(
    built: dict[str, Any], build: Callable[..., Any]
) -> None:
    build(redis_ssl=True, redis_username="worker").connect()

    assert (built["ssl"], built["username"]) == (True, "worker")


@pytest.mark.parametrize(
    ("url", "endpoint"),
    [
        ("rediss://:s3cret@cache:6390/0", ("cache", 6390, "default-user", "s3cret", True)),
        ("redis://cache", ("cache", 6379, "default-user", "shared", False)),
        ("redis://:s3cret@:6400", ("127.0.0.1", 6400, "default-user", "s3cret", False)),
        ("rediss://worker:s3cret@cache", ("cache", 6379, "worker", "s3cret", True)),
        ("redis://w%40rk:p%40ss%3A1@cache", ("cache", 6379, "w@rk", "p@ss:1", False)),
    ],
)
def test_a_url_endpoint_takes_tls_from_the_scheme_and_its_own_decoded_credentials_first(
    url: str, endpoint: tuple[Any, ...]
) -> None:
    assert endpoint_from_url(url, password="shared", username="default-user") == dict(
        zip(("redis_host", "redis_port", "redis_username", "redis_password", "redis_ssl"), endpoint, strict=True)
    )


def test_a_url_with_a_port_that_is_no_number_is_refused() -> None:
    with pytest.raises(ValueError, match="abc"):
        endpoint_from_url("redis://cache:abc")


def test_an_endpoint_password_is_read_stripped_from_the_named_file(
    bare_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "redis-password"
    secret.write_text("from-file\n")
    bare_env.setenv("REDIS_PASSWORD_FILE", str(secret))

    assert redis_endpoint_from_env("X")["redis_password"] == "from-file"


@pytest.mark.parametrize(
    "response",
    [ConnectionError("unavailable"), None, [], [{}], [{"times_delivered": "not-a-number"}], ["not-a-mapping"]],
)
def test_an_unreadable_delivery_count_is_zero(response: Any) -> None:
    assert _consumer().redis_delivery_count(_Pending(response), "1-0") == 0
