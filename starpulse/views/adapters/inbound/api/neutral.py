"""The request-in, response-out types every route handler is written against: no socket and no web framework, so the
ASGI app (and any other front) calls the same handlers."""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from contextlib import AbstractContextManager
from types import MappingProxyType
from typing import Any, NamedTuple, Protocol

from starpulse.views.adapters.inbound.compression import Encoded


class Arrival(NamedTuple):
    """A connection when it was accepted: the time, the request workers busy or about to be (itself included) and the
    streams open."""

    at: float
    busy: int = 0
    streams: int = 0


class Request(NamedTuple):
    """A GET as a server hands it over: the path, the raw query string, the client's address and the values its route's
    path template named."""

    path: str
    query: str
    client: str
    path_params: Mapping[str, str] = MappingProxyType({})


class Response(NamedTuple):
    """What a route answers, in the order a server's `_send` takes it. `retry_after` is the seconds a refused client is
    asked to wait; `close` ends the connection after the answer, since a request body was left unread."""

    body: bytes | Encoded
    status: int = 200
    cache: str = "no-store"
    content_type: str = "application/json"
    retry_after: int | None = None
    close: bool = False


class Headers(Protocol):
    """The request headers a write reads: a lookup by name that ignores case."""

    def get(self, name: str) -> str | None: ...


class WriteRequest(NamedTuple):
    """A POST, PUT or DELETE as a server hands it over: the method, the path, the client's address, the headers,
    `body`, which reads the given number of bytes of the request body (a server reads it only once a route wants it),
    and the values its route's path template named."""

    method: str
    path: str
    client: str
    headers: Headers
    body: Callable[[int], bytes]
    path_params: Mapping[str, str] = MappingProxyType({})


class Stream(NamedTuple):
    """An open stream: `frames` are the bytes to write, in order, until the client leaves (the caller then closes the
    generator); `release` detaches the stream from the feed once it ends."""

    frames: Generator[bytes]
    release: Callable[[], None]


Query = dict[str, list[str]]
Admit = Callable[[], bool]
Handler = Callable[[Request], Response]
WriteHandler = Callable[[WriteRequest], Response | None]
StreamHandler = Callable[[Request, Admit], Stream | Response]
#: Times a read: given the request, the seconds it queued and its arrival, a context the server holds open across the
#: send; the value it yields has a `computed()` the handler's caller calls once the answer is made.
Watch = Callable[[Request, float, Arrival], AbstractContextManager[Any]]


class ReadRoute(NamedTuple):
    """A GET at `path` (under `/api`), answered by `handler`; `watch`, when set, times each read."""

    path: str
    handler: Handler
    watch: Watch | None = None


class WriteRoute(NamedTuple):
    """The `methods` at `path` (under `/api`), answered by `handler`, which answers None where a deployment leaves the
    route unconfigured."""

    path: str
    methods: tuple[str, ...]
    handler: WriteHandler


class StreamRoute(NamedTuple):
    """A GET at `path` (under `/api`) that opens a stream, or is refused with a response. `handler` takes the request
    and `admit`, which moves the connection's worker into the stream pool and says whether there was room."""

    path: str
    handler: StreamHandler


ApiRoute = ReadRoute | WriteRoute | StreamRoute
