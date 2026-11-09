"""What the `/api` endpoints share: the response a body becomes, the worker thread a blocking read runs on, and the
seams and client address an endpoint takes from its request."""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from anyio import to_thread
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.compression import Encoded, accepts_gzip
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api

logger = logging.getLogger(__name__)

PLACE = "starpulse.place"  # in a request's scope: its place among the streams open
RAN = "starpulse.ran"  # in a timed request's scope: what its worker thread calls once it has the request


def _nothing() -> None:
    pass


def seams(request: Request) -> Api:
    """The seams the app's routes are made over."""
    return request.app.state.api


def target(request: Request) -> str:
    """The path as the client sent it, still percent-encoded: a route decodes what it takes from it."""
    raw = request.scope.get("raw_path")
    return raw.decode("ascii", "replace") if raw else request.scope["path"]


def query(request: Request) -> dict[str, list[str]]:
    """The values the request's query string names, by name."""
    return parse_qs(request.url.query)


def client(request: Request) -> str:
    return request.client.host if request.client else ""


def answer(
    request: Request,
    body: bytes | Encoded,
    status: int = 200,
    cache: str = "no-store",
    content_type: str = "application/json",
    retry_after: int | None = None,
    close: bool = False,
) -> Response:
    """`body` as `request` is answered: JSON unless told otherwise; an `Encoded` body is sent as the gzip it already
    holds to a page that accepts gzip, and any other is left to the `Gzip` middleware. `retry_after` is the seconds a
    refused client is asked to wait; `close` ends the connection after the answer, since a request body was left unread."""
    headers = {"content-type": content_type, "cache-control": cache}
    if isinstance(body, Encoded):
        gzipped = body.gzipped if accepts_gzip(request.headers.get("accept-encoding")) else None
        body = body.body if gzipped is None else gzipped
        if gzipped is not None:
            headers["content-encoding"] = "gzip"
    if retry_after is not None:
        headers["retry-after"] = str(retry_after)
    if close and request.scope["http_version"] != "2":  # HTTP/2 has no connection header, and a stream ends alone
        headers["connection"] = "close"
    if request.method == "HEAD":
        return Response(b"", status, headers | {"content-length": str(len(body))})
    return Response(body, status, headers)


def _built[T](request: Request, work: Callable[[], T]) -> T | Response:
    """What `work` returns, once the timing knows the request has it; a body its model refuses is a logged 500, since
    the page reads only what a model names."""
    request.scope.get(RAN, _nothing)()
    try:
        return work()
    except ValidationError:
        logger.exception("StarPulse: %s %s built a body its model refuses", request.method, request.url.path)
        return answer(request, encode("error", {"error": "the server built a body its contract refuses"}), 500)


async def on_worker(request: Request, work: Callable[[], Response]) -> Response:
    """Run `work` for `request` on a worker thread."""
    return await to_thread.run_sync(
        lambda: _built(request, work), abandon_on_cancel=True, limiter=request.app.state.workers
    )


def on_loop(request: Request, work: Callable[[], Response | None]) -> Response | None:
    """Run `work` for `request` on the event loop, which `work` must not block: a read that needs only what is in
    memory. Each hop to a worker thread and back is two wakeups, and on a busy host each waits its turn to run; `work`
    answers None for a request that needs a worker."""
    return _built(request, work)


def reading(work: Callable[[Request], Response]) -> Callable[[Request], Awaitable[Response]]:
    """`work`, which blocks, as a Starlette endpoint that runs it on a worker thread."""

    @functools.wraps(work)
    async def endpoint(request: Request) -> Response:
        return await on_worker(request, lambda: work(request))

    return endpoint
