"""The route tables' types: each route is a path and the Starlette endpoint that answers it."""

from collections.abc import Awaitable, Callable, Generator
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:  # annotation only
    from starlette.requests import Request as Incoming
    from starlette.responses import Response as Reply


class Stream(NamedTuple):
    """An open stream: `frames` are the bytes to write, in order, until the client leaves (the caller then closes the
    generator); `release` detaches the stream from the feed once it ends."""

    frames: Generator[bytes]
    release: Callable[[], None]


Endpoint = Callable[["Incoming"], Awaitable["Reply"]]


class ReadRoute(NamedTuple):
    """A GET at `path` (under `/api`), answered by the Starlette endpoint `handler`; `params` are the query names
    the handler reads, the request-duration histogram's shape vocabulary."""

    path: str
    handler: Endpoint
    params: frozenset[str] = frozenset()


class WriteRoute(NamedTuple):
    """The `methods` at `path` (under `/api`), answered by the Starlette endpoint `handler`."""

    path: str
    methods: tuple[str, ...]
    handler: Endpoint


ApiRoute = ReadRoute | WriteRoute
