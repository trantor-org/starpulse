"""The scheduler's switch.

- `GET /api/scheduler`: whether the scheduler runs.
- `PUT /api/scheduler`: turn it on or off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, client, reading, seams
from starpulse.views.adapters.inbound.api.neutral import ApiRoute, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole
from starpulse.views.application.commands.settings import scheduler as scheduler_command
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.neutral import WriteRequest
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def status(request: Request) -> Response:
    code, body = scheduler_command(client(request), "GET", b"", seams(request).services.scheduler)
    return answer(request, encode("scheduler", body), code)


def routes(api: Api) -> list[ApiRoute]:
    scheduler = api.services.scheduler

    def switch(request: WriteRequest) -> tuple[int, dict]:
        return scheduler_command(request.client, "PUT", whole(request), scheduler)

    return [ReadRoute("/scheduler", status), WriteRoute("/scheduler", ("PUT",), guarded("scheduler", switch))]
