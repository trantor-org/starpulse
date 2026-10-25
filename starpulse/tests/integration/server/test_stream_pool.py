"""Long-lived streams run from their own bounded pool, so a short request never waits behind them."""

import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from http.client import HTTPResponse
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import next_event, serve, url
from starpulse.pulls.pulls import PullStore
from starpulse._internal.server import asgi_app
from starpulse._internal.server.page_server import PageServer
from starpulse.tests.machines import MACHINES, ROLES

_STREAM = "/api/lanes"


@contextmanager
def _small_pools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requests: int, streams: int) -> Iterator[PageServer]:
    """A server whose request pool holds `requests` workers and whose stream pool holds `streams`."""
    monkeypatch.setattr(asgi_app, "REQUEST_THREADS", requests)
    monkeypatch.setattr(asgi_app, "STREAM_LIMIT", streams)
    store = PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), pulls=store, slow_read_s=0.0) as server:
        assert isinstance(server, PageServer)
        yield server


def _open(server: PageServer, stack: ExitStack) -> HTTPResponse:
    """A stream held open until `stack` closes, its first event read so its worker is known to be serving it."""
    resp = stack.enter_context(urllib.request.urlopen(url(server, _STREAM), timeout=5))
    next_event(resp)
    return resp


def test_a_full_stream_pool_does_not_delay_a_short_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    with _small_pools(tmp_path, monkeypatch, requests=2, streams=3) as server, ExitStack() as streams:
        for _ in range(3):
            _open(server, streams)

        started = time.monotonic()
        with urllib.request.urlopen(url(server, "/api/pulls"), timeout=5) as resp:
            status = resp.status
        elapsed = time.monotonic() - started
        assert server.drain(5)  # the read logs after its last byte is sent, which the client returns on

    (line,) = [r.getMessage() for r in caplog.records if "slow_read" in r.getMessage()]
    assert status == 200
    assert elapsed < 1
    assert float(re.search(r"queue_s=([0-9.]+)", line).group(1)) < 1  # type: ignore[union-attr]


def test_a_stream_over_the_cap_is_refused_with_retry_after_and_holds_no_request_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _small_pools(tmp_path, monkeypatch, requests=1, streams=1) as server, ExitStack() as streams:
        _open(server, streams)

        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(url(server, _STREAM), timeout=5)
        with urllib.request.urlopen(url(server, "/api/snapshot"), timeout=5) as resp:
            answered = resp.status

    assert refused.value.code == 503
    assert int(refused.value.headers["Retry-After"]) > 0
    assert json.load(refused.value)["error"]
    assert answered == 200


def test_a_closed_stream_frees_its_place_in_the_pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse._internal.server.streams._PING_S", 0.05)
    with _small_pools(tmp_path, monkeypatch, requests=1, streams=1) as server:
        with ExitStack() as first:
            _open(server, first)
        deadline = time.monotonic() + 5
        while server.app.open_streams and time.monotonic() < deadline:
            time.sleep(0.02)  # the stream ends when its next ping, or write, fails
        with ExitStack() as second:
            _open(server, second)  # refused with a 503 were the closed one's place still held
            assert server.app.open_streams == 1


def test_slow_read_names_the_busy_request_workers_and_open_streams_that_held_the_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    with _small_pools(tmp_path, monkeypatch, requests=4, streams=4) as server, ExitStack() as streams:
        _open(server, streams)
        _open(server, streams)
        urllib.request.urlopen(url(server, "/api/pulls"), timeout=5).read()
        assert server.drain(5)  # the read logs after its last byte is sent, which the client returns on

    (line,) = [r.getMessage() for r in caplog.records if "slow_read" in r.getMessage()]
    fields = dict(re.findall(r" (busy|streams)=([0-9]+)", line))
    assert fields == {"busy": "1", "streams": "2"}  # the read itself is the one busy worker
