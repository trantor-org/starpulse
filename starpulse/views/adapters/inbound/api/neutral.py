"""The route tables' types: each route is a path and the Starlette endpoint that answers it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Generator
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:  # annotation only
    from starlette.requests import Request as Incoming
    from starlette.responses import Response as Reply


class Arrival(NamedTuple):
    """A connection when it was accepted: the time, the request workers busy or about to be (itself included) and the
    streams open."""

    at: float
    busy: int = 0
    streams: int = 0


class Stream(NamedTuple):
    """An open stream: `frames` are the bytes to write, in order, until the client leaves (the caller then closes the
    generator); `release` detaches the stream from the feed once it ends."""

    frames: Generator[bytes]
    release: Callable[[], None]


Endpoint = Callable[["Incoming"], Awaitable["Reply"]]
#: Times a read: given the request and its arrival, a context the server holds open from that arrival to the last byte
#: sent; the value it yields has a `ran()` the server calls once a worker thread has taken the read and a `computed()` it
#: calls as the answer begins to be sent.
Watch = Callable[["Incoming", Arrival], AbstractContextManager[Any]]


class ReadRoute(NamedTuple):
    """A GET at `path` (under `/api`), answered by the Starlette endpoint `handler`; `watch`, when set, times each
    read."""

    path: str
    handler: Endpoint
    watch: Watch | None = None


class WriteRoute(NamedTuple):
    """The `methods` at `path` (under `/api`), answered by the Starlette endpoint `handler`."""

    path: str
    methods: tuple[str, ...]
    handler: Endpoint


class StreamRoute(NamedTuple):
    """A GET at `path` (under `/api`) that opens a stream, or is refused with a response, answered by the Starlette
    endpoint `handler`."""

    path: str
    handler: Endpoint


ApiRoute = ReadRoute | WriteRoute | StreamRoute
