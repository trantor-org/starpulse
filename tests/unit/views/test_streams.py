"""The streams are frame generators with no socket, so any server can write the frames."""

from __future__ import annotations

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.views.adapters.inbound.reads import Request, Response
from starpulse.views.adapters.inbound.snapshot_cache import SnapshotCache
from starpulse.views.adapters.inbound.streams import Stream, Streams

from tests.unit.views.routing import answer


@pytest.fixture
def streams(monkeypatch: pytest.MonkeyPatch) -> Streams:
    feed = BoardFeed()
    opened = Streams(feed, SnapshotCache(feed), lambda: "build-1")
    monkeypatch.setattr("starpulse.views.adapters.inbound.streams._PING_S", 0.01)
    return opened


def _open(streams: Streams, path: str, query: str = "", admit: bool = True) -> Stream | Response | None:
    return answer(streams.routes(), Request(path, query, "127.0.0.1"), lambda: admit)


def _stream(streams: Streams, path: str, query: str = "") -> Stream:
    opened = _open(streams, path, query)
    assert isinstance(opened, Stream)
    return opened


@pytest.mark.parametrize("path", ["/api/doctor", "/api/ledger/anything", "/api/move", "/", "/nothing"])
def test_a_path_that_is_no_stream_is_left_to_the_server(streams: Streams, path: str) -> None:
    assert _open(streams, path) is None


def test_the_board_stream_opens_with_its_snapshot_then_the_build(streams: Streams) -> None:
    opened = _stream(streams, "/api/events")
    try:
        assert next(opened.frames).startswith(b"event: snapshot\ndata: ")
        assert next(opened.frames) == b"event: build\ndata: build-1\n\n"
    finally:
        opened.frames.close()
        opened.release()


def test_a_snapshot_by_reference_names_the_path_to_read_it_from(streams: Streams) -> None:
    opened = _stream(streams, "/api/events", "snapshot=ref")
    try:
        assert next(opened.frames).startswith(b"event: snapshot\ndata: ref /api/events/body/")
    finally:
        opened.frames.close()
        opened.release()


def test_an_idle_stream_pings(streams: Streams) -> None:
    opened = _stream(streams, "/api/events")
    try:
        next(opened.frames)  # snapshot
        next(opened.frames)  # build
        assert next(opened.frames) == b": ping\n\n"
    finally:
        opened.frames.close()
        opened.release()


def test_a_stream_is_refused_when_the_pool_is_full(streams: Streams) -> None:
    refused = _open(streams, "/api/events", admit=False)

    assert isinstance(refused, Response)
    assert refused.status == 503
    assert refused.retry_after == 5


def test_a_held_stream_must_name_its_session_and_asks_for_no_room_first(streams: Streams) -> None:
    refused = answer(
        streams.routes(), Request("/api/held", "", "127.0.0.1"), lambda: pytest.fail("admitted before the 400")
    )

    assert isinstance(refused, Response)
    assert refused.status == 400


def test_a_ledger_stream_for_an_unknown_event_is_a_404(streams: Streams) -> None:
    refused = _open(streams, "/api/ledger/nothing/events")

    assert isinstance(refused, Response)
    assert refused.status == 404
