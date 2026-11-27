"""The Board's snapshot read, served as the Board writer stored it.

- `GET /api/snapshot`, `?view=full`, `GET /api/flows`: the one live payload the Board writer stored, to the page and the agent CLI alike.
"""

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def snapshot(request: Request) -> Response:
    return answer(request, seams(request).snapshots.stored()[1])


@reading
def flows(request: Request) -> Response:
    return answer(request, seams(request).snapshots.flows())


def routes(api: Api) -> list[ApiRoute]:
    return [
        ReadRoute("/snapshot", snapshot, params=frozenset({"view"})),
        ReadRoute("/flows", flows),
    ]
