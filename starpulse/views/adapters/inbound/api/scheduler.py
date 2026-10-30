"""The scheduler's switch.

- `GET /api/scheduler`: whether the scheduler runs.
- `PUT /api/scheduler`: turn it on or off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starpulse.views.adapters.inbound.api.neutral import ApiRoute, ReadRoute, Request, Response, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole
from starpulse.views.application.commands.settings import scheduler as scheduler_command
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.neutral import WriteRequest
    from starpulse.views.adapters.inbound.api.routing import Api


def routes(api: Api) -> list[ApiRoute]:
    scheduler = api.services.scheduler

    def status(request: Request) -> Response:
        code, body = scheduler_command(request.client, "GET", b"", scheduler)
        return Response(encode("scheduler", body), code)

    def switch(request: WriteRequest) -> tuple[int, dict]:
        return scheduler_command(request.client, "PUT", whole(request), scheduler)

    return [ReadRoute("/scheduler", status), WriteRoute("/scheduler", ("PUT",), guarded("scheduler", switch))]
