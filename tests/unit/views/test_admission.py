"""With every request worker busy, the app refuses each HTTP request with a 503 before any route sees it."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starpulse.runs.adapters.inbound.cloudevents_grpc import PATH as CLOUDEVENTS_GRPC_PATH
from starpulse.views.adapters.inbound import asgi_app
from starpulse.views.adapters.inbound.api.answering import answer, reading
from starpulse.views.adapters.inbound.api.table import ReadRoute, StreamRoute, WriteRoute
from starpulse.views.adapters.inbound.asgi_app import PageApp

from tests.unit.views.asgi import Answer, call


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, grpc=None) -> PageApp:
    monkeypatch.setattr(asgi_app, "REQUEST_THREADS", 1)
    routes = [
        ReadRoute("/read", reading(lambda request: answer(request, b"{}"))),
        WriteRoute("/write", ("POST",), reading(lambda request: answer(request, b"{}"))),
        StreamRoute("/held", reading(lambda request: answer(request, b"{}"))),
    ]
    return PageApp(routes, [], tmp_path, (), grpc=grpc)  # type: ignore[arg-type]


async def _with_every_worker_busy(app: PageApp, path: str, method: str) -> Answer:
    async with app._workers:  # the one worker the pool holds
        return await call(app, path, method)


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/read"), ("POST", "/api/write"), ("GET", "/api/held"), ("GET", "/"), ("GET", "/nothing")],
)
def test_every_route_answers_503_with_retry_after_while_no_worker_is_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    app = _app(tmp_path, monkeypatch)

    refused = asyncio.run(_with_every_worker_busy(app, path, method))

    assert refused.status == 503
    assert int(refused.headers["retry-after"]) >= 1


def test_a_route_answers_as_before_once_a_worker_is_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path, monkeypatch)

    assert asyncio.run(call(app, "/api/read")).status == 200


def test_the_grpc_path_is_not_refused_for_want_of_a_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def grpc(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = _app(tmp_path, monkeypatch, grpc)

    assert asyncio.run(_with_every_worker_busy(app, CLOUDEVENTS_GRPC_PATH, "POST")).status == 200
