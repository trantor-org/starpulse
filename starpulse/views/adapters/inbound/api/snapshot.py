"""The Board's snapshot: the event stream that carries it and the held and lane streams that follow it, the body a
`ref` snapshot event names (once), and the snapshot read itself, served as the Board writer stored it.

- `GET /api/events`, `/api/held`, `/api/lanes`: streams of the Board, a session's held tasks and its lanes.
- `GET /api/events/body/{key}`: the snapshot body a `ref` event names.
- `GET /api/snapshot`: the Board's snapshot, or the full one with `?view=full`.
- `GET /api/flows`: every flow whole, with the roles, settled tasks, pulls and runs the agent CLI reads beside them.
"""

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, query, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, StreamRoute
from starpulse.views.adapters.inbound.api.streams import streaming
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def body(request: Request) -> Response:
    key = request.path_params["key"]
    held = seams(request).snapshots.body(key)
    if held is None:
        return answer(request, encode("error", {"error": f"no snapshot {key} is held"}), 404)
    return answer(request, held, cache="max-age=3600, immutable")


@reading
def snapshot(request: Request) -> Response:
    view = "full" if query(request).get("view") == ["full"] else "slim"
    return answer(request, seams(request).snapshots.stored(view)[1])


@reading
def flows(request: Request) -> Response:
    return answer(request, seams(request).snapshots.flows())


def routes(api: Api) -> list[ApiRoute]:
    streams = api.streams
    return [
        StreamRoute("/events", streaming(streams.board)),
        StreamRoute("/held", streaming(streams.held)),
        StreamRoute("/lanes", streaming(streams.lanes)),
        ReadRoute("/events/body/{key:path}", body),
        ReadRoute("/snapshot", snapshot),
        ReadRoute("/flows", flows),
    ]
