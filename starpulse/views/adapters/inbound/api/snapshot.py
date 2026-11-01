"""The Board's snapshot: the event stream that carries it and the held and lane streams that follow it, the body a
`ref` snapshot event names (once), and the snapshot read itself, taken and encoded per request.

- `GET /api/events`, `/api/held`, `/api/lanes`: streams of the Board, a session's held tasks and its lanes.
- `GET /api/events/body/{key}`: the snapshot body a `ref` event names.
- `GET /api/snapshot`: the Board's snapshot, or the full one with `?view=full`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, query, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, StreamRoute
from starpulse.views.adapters.inbound.api.streams import streaming
from starpulse.views.model.encoding import encode, full_snapshot

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
    snapshots = seams(request).snapshots
    if query(request).get("view") == ["full"]:
        return answer(request, encode("snapshot", full_snapshot(snapshots.take().snapshot)))
    return answer(request, snapshots.build()[1])


def routes(api: Api) -> list[ApiRoute]:
    streams = api.streams
    return [
        StreamRoute("/events", streaming(streams.board)),
        StreamRoute("/held", streaming(streams.held)),
        StreamRoute("/lanes", streaming(streams.lanes)),
        ReadRoute("/events/body/{key:path}", body),
        ReadRoute("/snapshot", snapshot),
    ]
