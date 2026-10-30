"""The streams are frame generators with no socket, so any server can write the frames."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.views.adapters.inbound import asgi_app
from starpulse.views.adapters.inbound.api.neutral import Admit, Request, Response, Stream, StreamRoute
from starpulse.views.adapters.inbound.api.routing import Api
from starpulse.views.adapters.inbound.asgi_app import PageApp
from starpulse.views.adapters.inbound.snapshot_cache import SnapshotCache
from starpulse.views.ports.services import Services

from tests.fake_board import bare_board
from tests.unit.views.asgi import call
from tests.unit.views.routing import answer
from tests.unit.views.routing import streams as stream_routes


@pytest.fixture
def streams(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Api:
    feed = BoardFeed()
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    opened = Api(
        feed,
        HistoryStore("sqlite://", feed.machines),
        SnapshotCache(feed),
        HistoryWindow(feed, 6, log),
        bare_board(),
        Services(),
        build=lambda: "build-1",
    )
    monkeypatch.setattr("starpulse.views.adapters.inbound.api.streams._PING_S", 0.01)
    return opened


def _open(streams: Api, path: str, query: str = "", admit: bool = True) -> Stream | Response | None:
    return answer(stream_routes(streams), Request(path, query, "127.0.0.1"), lambda: admit)


def _stream(streams: Api, path: str, query: str = "") -> Stream:
    opened = _open(streams, path, query)
    assert isinstance(opened, Stream)
    return opened


@pytest.mark.parametrize("path", ["/api/doctor", "/api/ledger/anything", "/api/move", "/", "/nothing"])
def test_a_path_that_is_no_stream_is_left_to_the_server(streams: Api, path: str) -> None:
    assert _open(streams, path) is None


def test_the_board_stream_opens_with_its_snapshot_then_the_build(streams: Api) -> None:
    opened = _stream(streams, "/api/events")
    try:
        assert next(opened.frames).startswith(b"event: snapshot\ndata: ")
        assert next(opened.frames) == b"event: build\ndata: build-1\n\n"
    finally:
        opened.frames.close()
        opened.release()


def test_a_snapshot_by_reference_names_the_path_to_read_it_from(streams: Api) -> None:
    opened = _stream(streams, "/api/events", "snapshot=ref")
    try:
        assert next(opened.frames).startswith(b"event: snapshot\ndata: ref /api/events/body/")
    finally:
        opened.frames.close()
        opened.release()


def test_an_idle_stream_pings(streams: Api) -> None:
    opened = _stream(streams, "/api/events")
    try:
        next(opened.frames)  # snapshot
        next(opened.frames)  # build
        assert next(opened.frames) == b": ping\n\n"
    finally:
        opened.frames.close()
        opened.release()


def test_a_stream_is_refused_when_the_pool_is_full(streams: Api) -> None:
    refused = _open(streams, "/api/events", admit=False)

    assert isinstance(refused, Response)
    assert refused.status == 503
    assert refused.retry_after == 5


def test_a_held_stream_must_name_its_session_and_asks_for_no_room_first(streams: Api) -> None:
    refused = answer(
        stream_routes(streams), Request("/api/held", "", "127.0.0.1"), lambda: pytest.fail("admitted before the 400")
    )

    assert isinstance(refused, Response)
    assert refused.status == 400


def test_a_ledger_stream_for_an_unknown_event_is_a_404(streams: Api) -> None:
    refused = _open(streams, "/api/ledger/nothing/events")

    assert isinstance(refused, Response)
    assert refused.status == 404


def _frames() -> Generator[bytes]:
    while True:
        time.sleep(0.005)
        yield b": ping\n\n"


def _held_app(tmp_path: Path, handler: Callable[[Request, Admit], Stream | Response]) -> PageApp:
    return PageApp([StreamRoute("/held", handler)], [], None, tmp_path, ())  # type: ignore[arg-type]


def test_a_stream_the_client_leaves_gives_its_place_back_once(tmp_path: Path) -> None:
    during: list[int] = []

    def handler(request: Request, admit: Admit) -> Stream | Response:
        assert admit()
        during.append(app.open_streams)
        return Stream(_frames(), lambda: None)

    app = _held_app(tmp_path, handler)

    assert asyncio.run(call(app, "/api/held", leave_at_first_frame=True)).status == 200
    assert (during, app.open_streams) == ([1], 0)


def test_a_stream_the_pool_refuses_takes_no_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asgi_app, "STREAM_LIMIT", 0)

    def handler(request: Request, admit: Admit) -> Stream | Response:
        return Stream(_frames(), lambda: None) if admit() else Response(b"{}", 503, retry_after=5)

    app = _held_app(tmp_path, handler)
    refused = asyncio.run(call(app, "/api/held"))

    assert (refused.status, refused.headers["retry-after"], app.open_streams) == (503, "5", 0)


def test_a_stream_admitted_and_then_refused_gives_its_place_back_once(tmp_path: Path) -> None:
    def handler(request: Request, admit: Admit) -> Stream | Response:
        assert admit()
        return Response(b"{}", 404)

    app = _held_app(tmp_path, handler)

    assert asyncio.run(call(app, "/api/held")).status == 404
    assert app.open_streams == 0


def test_a_stream_whose_handler_fails_gives_its_place_back_once(tmp_path: Path) -> None:
    def handler(request: Request, admit: Admit) -> Stream | Response:
        assert admit()
        raise RuntimeError("the ledger broke")

    app = _held_app(tmp_path, handler)

    with pytest.raises(RuntimeError):
        asyncio.run(call(app, "/api/held"))
    assert app.open_streams == 0
