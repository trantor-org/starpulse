"""Gzip for what the server writes to a page that accepts it: a body over `MIN_BYTES` and every stream event, by
Starlette's `GZipMiddleware`, and the snapshot bodies held once, gzipped, for many pages."""

from __future__ import annotations

import gzip
from typing import NamedTuple

from starlette.datastructures import Headers
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

#: A body this size or smaller is sent as it is: gzip's header and the page's decode cost more than it saves.
MIN_BYTES = 64 * 1024
#: Level 6 is what the stream's small events and a one-off body are sent at: it gives nearly the size level 9 does.
LEVEL = 6
#: What a body held for many pages is compressed at, since the page that finds it out of date waits for it: the 4.9 MB
#: snapshot takes ~190 ms at level 6 and ~60 ms at level 1, which is 22% larger.
HELD_LEVEL = 1


def accepts_gzip(accept_encoding: str | None) -> bool:
    """Whether an `Accept-Encoding` header lists `gzip` with a quality above zero."""
    for item in (accept_encoding or "").split(","):
        coding, _, params = item.partition(";")
        if coding.strip().lower() == "gzip":
            return params.replace(" ", "").lower() not in ("q=0", "q=0.0", "q=0.00", "q=0.000")
    return False


class Encoded(NamedTuple):
    """A body and its gzip, made once for a body many pages read: gzip of a ~1 MB body takes tens of ms."""

    body: bytes
    #: None when the body is too small to be worth compressing.
    gzipped: bytes | None

    @classmethod
    def of(cls, body: bytes) -> Encoded:
        return cls(body, gzip.compress(body, compresslevel=HELD_LEVEL, mtime=0) if len(body) > MIN_BYTES else None)


class Gzip(GZipMiddleware):
    """`GZipMiddleware` at this server's levels: a body over `MIN_BYTES` goes to a thread rather than the event loop, an
    event stream is compressed with a flush after each event so a page decodes it as it arrives, and `gzip;q=0` is
    a refusal, which `GZipMiddleware` reads as an offer. A response that holds its own gzip (`Encoded`) is left as it is."""

    def __init__(self, app: ASGIApp) -> None:
        excluded = tuple(kind for kind in DEFAULT_EXCLUDED_CONTENT_TYPES if kind != "text/event-stream")
        super().__init__(
            app,
            minimum_size=MIN_BYTES,
            compresslevel=LEVEL,
            thread_minimum_size=MIN_BYTES,
            exclude_content_types=excluded,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not accepts_gzip(Headers(scope=scope).get("accept-encoding")):
            kept = [(name, value) for name, value in scope["headers"] if name != b"accept-encoding"]
            scope = {**scope, "headers": kept}
        await super().__call__(scope, receive, send)
