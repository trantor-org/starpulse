"""Admin's settings.

- `GET /api/admin`: the scheduler's state, the display and the theme.
- `PUT /api/admin`: change any of them, naming only the fields that change.
"""

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, client, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole
from starpulse.views.application.commands.settings import admin as admin_command
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def status(request: Request) -> Response:
    services = seams(request).services
    code, body = admin_command(client(request), "GET", b"", services.scheduler, services.display)
    return answer(request, encode("admin", body), code)


def routes(api: Api) -> list[ApiRoute]:
    services = api.services

    def change(request: Request) -> tuple[int, dict]:
        return admin_command(client(request), "PUT", whole(request), services.scheduler, services.display)

    return [ReadRoute("/admin", status), WriteRoute("/admin", ("PUT",), guarded("admin", change))]
