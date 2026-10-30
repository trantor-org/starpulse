"""Answer a request from a route table the way the ASGI app's router reaches it: the first route in order whose path
template matches and whose methods include the request's."""

from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import unquote

from starlette.routing import compile_path


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


def answer(table: Sequence[tuple], request: Any, *extra: Any) -> Any:
    """What the route `request` reaches answers it with, its path template's values in `path_params`, or None where it
    reaches no route."""
    matched = _match(table, request.path, getattr(request, "method", "GET"))
    if matched is None:
        return None
    handler, params = matched
    return handler(request._replace(path_params=params), *extra)
