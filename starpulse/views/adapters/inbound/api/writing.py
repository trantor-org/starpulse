"""What every write route shares: the refusal of a request another web page may have sent, the body read, the answer
and the token-guarded push."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable

from anyio import from_thread
from starlette.requests import ClientDisconnect, Request
from starlette.responses import PlainTextResponse, Response

from starpulse.board.model.seam import OPERATOR, Written
from starpulse.views.adapters.inbound.api.answering import answer, client, on_worker
from starpulse.views.application.commands.guard import RETRY_AFTER_S, write_refusal
from starpulse.views.model.encoding import encode

TaskWrite = Callable[[str, bytes], tuple[int, dict]]
Pushed = Callable[[str | None, bytes], tuple[int, dict]]

_BODY = "starpulse.body"  # in a write's scope: its `_Body`


def no_writer(task: str, status: str, actor: str = OPERATOR) -> Written:
    return Written(False, "no board writer is configured", unavailable=True)


class _Body:
    """A request's body, read by a worker thread only as much as a route asks for: a push over its limit is refused
    without the body being taken off the wire."""

    def __init__(self, request: Request) -> None:
        self._chunks = request.stream()
        self._held = bytearray()

    async def _read(self, size: int) -> bytes:
        while len(self._held) < size and (chunk := await anext(self._chunks, b"")):
            self._held += chunk
        taken = bytes(self._held[:size])
        del self._held[:size]
        return taken

    def __call__(self, size: int) -> bytes:
        return from_thread.run(self._read, size) if size > 0 else b""


def writing(work: Callable[[Request], Response | None]) -> Callable[[Request], Awaitable[Response]]:
    """`work`, which blocks, as a Starlette endpoint that runs it on a worker thread; it answers None where a deployment
    leaves the route unconfigured. A write is answered once the snapshot read after it holds what it published."""

    @functools.wraps(work)
    async def endpoint(request: Request) -> Response:
        request.scope[_BODY] = _Body(request)

        def run() -> Response:
            try:
                response = work(request)
            except ClientDisconnect:
                return Response(status_code=400)  # the client left mid-body; nobody reads this
            if response is None:
                return PlainTextResponse("Not Found", 404)
            return response

        return await on_worker(request, run)

    return endpoint


def answered(request: Request, kind: str, body: dict, status: int) -> Response:
    """The write's answer; a 503 asks the client to send it again after `RETRY_AFTER_S`."""
    return answer(request, encode(kind, body), status, retry_after=RETRY_AFTER_S if status == 503 else None)


def refused(request: Request) -> Response | None:
    """The refusal of a write another web page may have sent, or None."""
    headers = request.headers
    refusal = write_refusal(headers.get("Origin"), headers.get("Host"), headers.get("Content-Type"))
    return None if refusal is None else answer(request, encode("error", refusal[1]), refusal[0])


def body(request: Request, size: int) -> bytes:
    """The next `size` bytes of the request's body, read from a worker thread."""
    return request.scope[_BODY](size)


def whole(request: Request) -> bytes:
    return body(request, int(request.headers.get("Content-Length") or 0))


def guarded(kind: str, work: Callable[[Request], tuple[int, dict]]) -> Callable[[Request], Awaitable[Response]]:
    """`work` as a `kind` body, unless another web page may have sent the request."""

    def handle(request: Request) -> Response:
        refusal = refused(request)
        if refusal is not None:
            return refusal
        status, answered_body = work(request)
        return answered(request, kind, answered_body, status)

    return writing(handle)


def whole_body(handler: TaskWrite) -> Callable[[Request], tuple[int, dict]]:
    """`handler` over the client's address and the request's whole body."""
    return lambda request: handler(client(request), whole(request))


def pushed(request: Request, kind: str, ingest: Pushed, limit: int) -> Response:
    """Answer one token-guarded push; a body over `limit` is refused unread and the connection closed, since the body
    it left cannot be skipped."""
    try:
        declared = int(request.headers.get("Content-Length") or 0)
    except ValueError:
        declared = 0
    if declared > limit:
        return answer(request, encode(kind, {"error": f"a body is at most {limit} bytes"}), 413, close=True)
    status, result = ingest(request.headers.get("Authorization"), body(request, max(declared, 0)))
    return answered(request, kind, result, status)
