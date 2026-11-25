"""Admin's settings.

- `GET /api/admin`: the scheduler's state, the display and the theme, and the stream position a `schedulerChanges`
  subscription follows from.
- `PUT /api/admin`: change any of them, naming only the fields that change; it answers the same state.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, client, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole
from starpulse.views.application.commands.settings import admin as admin_command
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


def _at(position: Callable[[], int], run: Callable[[], tuple[int, dict[str, Any]]]) -> tuple[int, dict[str, Any]]:
    """`run`'s answer with the stream position read before it, so a subscription from it misses no status change."""
    at = position()
    code, body = run()
    return code, {**body, "position": at} if code == 200 else body


@reading
def status(request: Request) -> Response:
    api = seams(request)
    services = api.services
    code, body = _at(
        api.snapshots.position, lambda: admin_command(client(request), "GET", b"", services.scheduler, services.display)
    )
    return answer(request, encode("admin", body), code)


def routes(api: Api) -> list[ApiRoute]:
    services = api.services

    def change(request: Request) -> tuple[int, dict]:
        return _at(
            api.snapshots.position,
            lambda: admin_command(client(request), "PUT", whole(request), services.scheduler, services.display),
        )

    return [ReadRoute("/admin", status), WriteRoute("/admin", ("PUT",), guarded("admin", change))]
