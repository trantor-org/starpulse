"""Drives a `PageApp` in process: one request in, the answer's status, headers and body out, no socket."""

from __future__ import annotations

import asyncio
from typing import Any, NamedTuple


class Answer(NamedTuple):
    status: int
    headers: dict[str, str]
    body: bytes


async def call(app: Any, path: str, method: str = "GET", *, leave_at_first_frame: bool = False) -> Answer:
    """What `app` answers `method` `path`; with `leave_at_first_frame`, the client disconnects once it has been sent
    its first chunk of body."""
    sent: list[dict[str, Any]] = []
    left, asked = asyncio.Event(), False

    async def receive() -> dict[str, Any]:
        nonlocal asked
        if not asked:
            asked = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await left.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)
        if leave_at_first_frame and message["type"] == "http.response.body":
            left.set()

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1),
        "root_path": "",
        "http_version": "1.1",
    }
    await app(scope, receive, send)
    start = sent[0]
    headers = {name.decode().lower(): value.decode() for name, value in start["headers"]}
    return Answer(start["status"], headers, b"".join(message.get("body", b"") for message in sent[1:]))
