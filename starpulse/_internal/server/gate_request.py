"""The request a gate (the test host's write watch) judges and answers through, without a socket or `http.server`."""

from __future__ import annotations

import io
from typing import Protocol


class GateHeaders(Protocol):
    """The request headers a gate reads: a lookup by name that ignores case."""

    def get(self, name: str, default: str | None = None) -> str | None: ...


class GateRequest:
    """One request as a gate sees it: the method, the target (path and query) and the headers. A gate that refuses it
    answers through `send_response`, `send_header`, `end_headers` and `wfile`, which this collects as `status`,
    `sent` (every header, a name repeated as it was sent) and `wfile`'s bytes."""

    def __init__(self, command: str, path: str, headers: GateHeaders) -> None:
        self.command = command
        self.path = path
        self.headers = headers
        self.status = 200
        self.sent: list[tuple[str, str]] = []
        self.wfile = io.BytesIO()

    def send_response(self, code: int) -> None:
        self.status = code

    def send_header(self, name: str, value: str) -> None:
        self.sent.append((name, value))

    def end_headers(self) -> None:
        """A gate's answer is whole once its body is written; nothing is flushed here."""
