"""The stream routes are Starlette endpoints: a refused stream is a response, an open one writes its frames until the
client leaves, and the place it took among the streams open is given back once."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Generator
from pathlib import Path

import pytest
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.views.adapters.inbound import asgi_app
from starpulse.views.adapters.inbound.api import metrics
from starpulse.views.adapters.inbound.api.answering import PLACE
from starpulse.views.adapters.inbound.api.table import Stream, StreamRoute
from starpulse.views.adapters.inbound.api.routing import Api, api_routes
from starpulse.views.adapters.inbound.api.streams import Events, streaming
from starpulse.views.adapters.inbound.asgi_app import PageApp
from starpulse.views.adapters.inbound.snapshots import Snapshots
from starpulse.views.ports.services import Services

from tests.fake_board import bare_board
from tests.unit.views.asgi import call
from tests.unit.views.routing import handler_for
from tests.unit.views.routing import streams as stream_routes


@pytest.fixture
def streams(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Api:
    feed = BoardFeed()
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    opened = Api(
        feed,
        HistoryStore("sqlite://", feed.machines),
        Snapshots(feed),
        HistoryWindow(feed, 6, log),
        bare_board(),
        Services(),
        build=lambda: "build-1",
    )
    monkeypatch.setattr("starpulse.views.adapters.inbound.api.streams._PING_S", 0.01)
    return opened


def _app(streams: Api, tmp_path: Path) -> PageApp:
    return PageApp(api_routes(streams), metrics.routes, tmp_path, (), seams=streams)


@pytest.mark.parametrize("path", ["/api/doctor", "/api/ledger/anything", "/api/move", "/", "/nothing"])
def test_a_path_that_is_no_stream_route_is_no_stream(streams: Api, path: str) -> None:
    assert handler_for(stream_routes(streams), path) is None


def test_the_board_stream_opens_with_its_snapshot_then_the_build(streams: Api, tmp_path: Path) -> None:
    opened = asyncio.run(call(_app(streams, tmp_path), "/api/events", leave_after=2))

    assert (opened.status, opened.headers["content-type"]) == (200, "text/event-stream")
    assert opened.body.startswith(b"event: snapshot\ndata: ")
    assert b"event: build\ndata: build-1\n\n" in opened.body


def test_a_snapshot_by_reference_names_the_path_to_read_it_from(streams: Api, tmp_path: Path) -> None:
    opened = asyncio.run(call(_app(streams, tmp_path), "/api/events", query="snapshot=ref", leave_after=1))

    assert opened.body.startswith(b"event: snapshot\ndata: ref /api/events/body/")


def test_an_idle_stream_pings(streams: Api, tmp_path: Path) -> None:
    opened = asyncio.run(call(_app(streams, tmp_path), "/api/events", leave_after=3))

    assert b": ping\n\n" in opened.body


def test_a_head_request_gets_a_streams_headers_and_opens_none(streams: Api, tmp_path: Path) -> None:
    app = _app(streams, tmp_path)
    opened = asyncio.run(call(app, "/api/events", "HEAD"))

    assert (opened.status, opened.headers["content-type"], app.open_streams) == (200, "text/event-stream", 0)


def test_a_stream_is_refused_with_a_503_when_the_pool_is_full(
    streams: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(asgi_app, "STREAM_LIMIT", 0)
    client = TestClient(_app(streams, tmp_path), client=("127.0.0.1", 50000))

    refused = client.get("/api/events")

    assert (refused.status_code, refused.headers["retry-after"]) == (503, "5")
    assert "too many open streams" in refused.json()["error"]


def test_a_held_stream_must_name_its_session_and_asks_for_no_room_first(
    streams: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(asgi_app, "STREAM_LIMIT", 0)  # a 503 if it asked for room before the 400
    client = TestClient(_app(streams, tmp_path), client=("127.0.0.1", 50000))

    assert client.get("/api/held").status_code == 400


def test_a_ledger_stream_for_an_unknown_event_is_a_404(streams: Api, tmp_path: Path) -> None:
    client = TestClient(_app(streams, tmp_path), client=("127.0.0.1", 50000))

    assert client.get("/api/ledger/nothing/events").status_code == 404


def _frames(count: int | None = None) -> Generator[bytes]:
    sent = 0
    while count is None or sent < count:
        time.sleep(0.005)
        sent += 1
        yield b": ping\n\n"


def _held_app(tmp_path: Path, handler) -> PageApp:
    return PageApp([StreamRoute("/held", streaming(handler))], [], tmp_path, ())  # type: ignore[arg-type]


def _opened(request: Request, frames: Generator[bytes], released: list[str] | None = None) -> Response:
    stream = Stream(frames, lambda: released.append("released") if released is not None else None)
    return Events(request, stream)


def test_a_stream_that_ends_gives_its_place_back_once(tmp_path: Path) -> None:
    during: list[int] = []

    def handler(request: Request) -> Response:
        assert request.scope[PLACE].take()
        during.append(app.open_streams)
        return _opened(request, _frames(3))

    app = _held_app(tmp_path, handler)

    response = TestClient(app).get("/api/held")

    assert (response.status_code, response.content, during, app.open_streams) == (200, b": ping\n\n" * 3, [1], 0)


def test_a_stream_the_client_leaves_gives_its_place_back_once(tmp_path: Path) -> None:
    during: list[int] = []
    released: list[str] = []

    def handler(request: Request) -> Response:
        assert request.scope[PLACE].take()
        during.append(app.open_streams)
        return _opened(request, _frames(), released)

    app = _held_app(tmp_path, handler)

    assert asyncio.run(call(app, "/api/held", leave_after=1)).status == 200
    assert (during, app.open_streams, released) == ([1], 0, ["released"])


def test_a_stream_the_pool_refuses_takes_no_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asgi_app, "STREAM_LIMIT", 0)

    def handler(request: Request) -> Response:
        if request.scope[PLACE].take():
            return _opened(request, _frames())
        return Response(b"{}", 503, {"retry-after": "5"})

    app = _held_app(tmp_path, handler)
    refused = TestClient(app).get("/api/held")

    assert (refused.status_code, refused.headers["retry-after"], app.open_streams) == (503, "5", 0)


def test_a_stream_admitted_and_then_refused_gives_its_place_back_once(tmp_path: Path) -> None:
    def handler(request: Request) -> Response:
        assert request.scope[PLACE].take()
        return Response(b"{}", 404)

    app = _held_app(tmp_path, handler)

    assert TestClient(app).get("/api/held").status_code == 404
    assert app.open_streams == 0


def test_a_stream_whose_handler_fails_gives_its_place_back_once(tmp_path: Path) -> None:
    def handler(request: Request) -> Response:
        assert request.scope[PLACE].take()
        raise RuntimeError("the ledger broke")

    app = _held_app(tmp_path, handler)

    with pytest.raises(RuntimeError):
        TestClient(app).get("/api/held")
    assert app.open_streams == 0
