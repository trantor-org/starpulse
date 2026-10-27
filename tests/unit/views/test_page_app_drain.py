"""A stopping Page API child waits for a request the app has taken, not only for one that has reached its endpoint."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starpulse.views.asgi_app import PageApp


def test_drained_waits_for_a_request_taken_before_its_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def exchange() -> tuple[bool, bool]:
        bare = SimpleNamespace(routes=list)  # no route: the stub below answers
        app = PageApp(bare, bare, bare, None, tmp_path, ())  # type: ignore[arg-type]
        taken, release = asyncio.Event(), asyncio.Event()

        async def before_the_endpoint(scope: Any, receive: Any, send: Any) -> None:
            taken.set()
            await release.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        monkeypatch.setattr(app, "_app", before_the_endpoint)

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            return None

        scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}
        asking = asyncio.ensure_future(app(scope, receive, send))
        await taken.wait()
        blocked = await app.drained(0.05)
        release.set()
        await asking
        return blocked, await app.drained(0.05)

    assert asyncio.run(exchange()) == (False, True)
