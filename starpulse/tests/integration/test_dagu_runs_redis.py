"""The `runs:events` stream against a real Redis: the view lists Dagu once per connect and runs move its DAGs."""

from __future__ import annotations

import time

import pytest
import redis as redis_lib

from starpulse import run_events
from starpulse.board_feed import BoardFeed
from starpulse.dagu import DaguRuns, build_runs_consumer, dags
from starpulse.streams import StreamConsumer, StreamProducer
from starpulse.tests.dagu_stub import dagu

LISTING = "/api/v1/dags?perPage=200"


def status_of(feed: BoardFeed) -> str:
    return feed.snapshot()["dags"][0]["status"]


@pytest.fixture
def on_test_redis(redis_client: redis_lib.Redis, monkeypatch: pytest.MonkeyPatch) -> StreamProducer:
    """The consumer's connection is the test Redis; returns the producer for the stream the Dagu hook's entries are read from."""
    monkeypatch.setattr(StreamConsumer, "connect", lambda self: redis_client)
    return StreamProducer(stream=run_events.STREAM, client_factory=lambda: redis_client)


def hook_entry(phase: str, status: str) -> dict:
    return run_events.entry(phase, "d1", "r1", status, now=time.time())


def test_a_run_published_while_the_view_lists_dagu_still_reaches_it(on_test_redis: StreamProducer) -> None:
    with dagu({"d1": ["a"]}) as (base_url, calls):
        feed = BoardFeed()
        runs = DaguRuns(feed.runs("ci"), lambda only=None: dags(base_url, only))

        def list_then_run_starts() -> None:
            runs.reconcile()
            on_test_redis.emit(hook_entry("start", "running"))

        consumer = build_runs_consumer(runs, "flow-view-test", on_connect=list_then_run_starts)
        consumer.read_block_ms = 100
        client = consumer.connect()
        consumer.consume_once(client)
        assert status_of(feed) == "running"

        on_test_redis.emit(hook_entry("end", "failed"))
        consumer.consume_once(client)

    assert status_of(feed) == "failed"
    assert calls.count(LISTING) == 2  # the connect's listing, then the ended run's step read


def test_every_connect_reads_dagu_again(on_test_redis: StreamProducer) -> None:
    with dagu({"d1": ["a"]}) as (base_url, calls):
        runs = DaguRuns(BoardFeed().runs("ci"), lambda only=None: dags(base_url, only))
        consumer = build_runs_consumer(runs, "flow-view-test")

        consumer.connect()
        consumer.connect()

    assert calls.count(LISTING) == 2
