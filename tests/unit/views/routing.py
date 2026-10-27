"""Answer a request from a route table the way the ASGI app's router reaches it: the first route in order whose path
template matches and whose methods include the request's."""

from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import unquote

from starlette.routing import compile_path


def handler_for(table: Sequence[tuple], path: str, method: str = "GET") -> Callable[..., Any] | None:
    """The handler of the first route of `table` (`(path, handler)` or `(path, methods, handler)`) that answers
    `method` at `path`, or None."""
    for route in table:
        template, handler = route[0], route[-1]
        methods = route[1] if len(route) == 3 else ("GET",)
        regex, _, _ = compile_path(template)
        if method in methods and regex.match(unquote(path)):
            return handler
    return None


def answer(table: Sequence[tuple], request: Any, *extra: Any) -> Any:
    """What the route `request` reaches answers it with, or None where it reaches no route."""
    handler = handler_for(table, request.path, getattr(request, "method", "GET"))
    return None if handler is None else handler(request, *extra)
