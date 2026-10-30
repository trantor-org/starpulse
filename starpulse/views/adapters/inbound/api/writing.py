"""What every write route shares: the refusal of a request another web page may have sent, the body read, the answer
and the token-guarded push."""

from __future__ import annotations

from collections.abc import Callable

from starpulse.board.model.seam import OPERATOR, Written
from starpulse.views.adapters.inbound.api.neutral import Response, WriteHandler, WriteRequest
from starpulse.views.application.commands.guard import RETRY_AFTER_S, write_refusal
from starpulse.views.model.encoding import encode

TaskWrite = Callable[[str, bytes], tuple[int, dict]]
Pushed = Callable[[str | None, bytes], tuple[int, dict]]


def no_writer(task: str, status: str, actor: str = OPERATOR) -> Written:
    return Written(False, "no board writer is configured", unavailable=True)


def answered(kind: str, body: dict, status: int) -> Response:
    """The write's answer; a 503 asks the client to send it again after `RETRY_AFTER_S`."""
    return Response(encode(kind, body), status, retry_after=RETRY_AFTER_S if status == 503 else None)


def refused(request: WriteRequest) -> Response | None:
    """The refusal of a write another web page may have sent, or None."""
    headers = request.headers
    refusal = write_refusal(headers.get("Origin"), headers.get("Host"), headers.get("Content-Type"))
    return None if refusal is None else Response(encode("error", refusal[1]), refusal[0])


def whole(request: WriteRequest) -> bytes:
    return request.body(int(request.headers.get("Content-Length") or 0))


def guarded(kind: str, answer: Callable[[WriteRequest], tuple[int, dict]]) -> WriteHandler:
    """`answer` as a `kind` body, unless another web page may have sent the request."""

    def handle(request: WriteRequest) -> Response:
        refusal = refused(request)
        if refusal is not None:
            return refusal
        status, body = answer(request)
        return answered(kind, body, status)

    return handle


def whole_body(handler: TaskWrite) -> Callable[[WriteRequest], tuple[int, dict]]:
    """`handler` over the client's address and the request's whole body."""
    return lambda request: handler(request.client, whole(request))


def pushed(request: WriteRequest, kind: str, ingest: Pushed, limit: int) -> Response:
    """Answer one token-guarded push; a body over `limit` is refused unread and the connection closed, since the body
    it left cannot be skipped."""
    try:
        declared = int(request.headers.get("Content-Length") or 0)
    except ValueError:
        declared = 0
    if declared > limit:
        return Response(encode(kind, {"error": f"a body is at most {limit} bytes"}), 413, close=True)
    status, body = ingest(request.headers.get("Authorization"), request.body(max(declared, 0)))
    return answered(kind, body, status)
