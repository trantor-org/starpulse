"""Answer a request from a route table the way the ASGI app's router reaches it: the first route in order whose path
template matches and whose methods include the request's."""

from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import unquote

from starlette.routing import compile_path
from starpulse.views.adapters.inbound.api import metrics
from starpulse.views.adapters.inbound.api.table import ReadRoute, StreamRoute, WriteRoute
from starpulse.views.adapters.inbound.api.routing import Api, api_routes


def table(api: Api, *kinds: type) -> list[tuple]:
    """The routes of `api` in match order as `(path, handler)` (a read or a stream) or `(path, methods, handler)` (a
    write), the `/api` mount in front of each path, limited to the `kinds` of route given (all by default)."""
    mounted = [
        *((route, "/api" + route.path) for route in api_routes(api)),
        *((route, route.path) for route in metrics.routes),
    ]
    return [
        (path, route.methods, route.handler) if isinstance(route, WriteRoute) else (path, route.handler)
        for route, path in mounted
        if not kinds or isinstance(route, kinds)
    ]


def reads(api: Api) -> list[tuple]:
    return table(api, ReadRoute)


def writes(api: Api) -> list[tuple]:
    return table(api, WriteRoute)


def streams(api: Api) -> list[tuple]:
    return table(api, StreamRoute)


def _match(table: Sequence[tuple], path: str, method: str) -> tuple[Callable[..., Any], dict[str, str]] | None:
    for route in table:
        template, handler = route[0], route[-1]
        methods = route[1] if len(route) == 3 else ("GET",)
        regex, _, convertors = compile_path(template)
        found = regex.match(unquote(path))
        if method in methods and found:
            return handler, {name: convertors[name].convert(value) for name, value in found.groupdict().items()}
    return None


def handler_for(table: Sequence[tuple], path: str, method: str = "GET") -> Callable[..., Any] | None:
    """The handler of the first route of `table` (`(path, handler)` or `(path, methods, handler)`) that answers
    `method` at `path`, or None."""
    matched = _match(table, path, method)
    return None if matched is None else matched[0]
