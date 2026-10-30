"""The Board's snapshot: the event stream that carries it and the held and lane streams that follow it, the body a
`ref` snapshot event names, and the snapshot read itself.

- `GET /api/events`, `/api/held`, `/api/lanes`: streams of the Board, a session's held tasks and its lanes.
- `GET /api/events/body/{key}`: the snapshot body a `ref` event names.
- `GET /api/snapshot`: the Board's snapshot, or the full one with `?view=full`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from starpulse.views.adapters.inbound.api.neutral import ApiRoute, ReadRoute, Request, Response, StreamRoute
from starpulse.views.model.encoding import encode, full_snapshot

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


def routes(api: Api) -> list[ApiRoute]:
    streams, snapshots = api.streams, api.snapshots

    def body(request: Request) -> Response:
        key = request.path_params["key"]
        held = snapshots.body(key)
        if held is None:
            return Response(encode("error", {"error": f"no snapshot {key} is held"}), 404)
        return Response(held, cache="max-age=3600, immutable")

    def snapshot(request: Request) -> Response:
        if parse_qs(request.query).get("view") == ["full"]:
            return Response(encode("snapshot", full_snapshot(snapshots.read().snapshot)))
        return Response(snapshots.read().encoded)

    return [
        StreamRoute("/events", streams.board),
        StreamRoute("/held", streams.held),
        StreamRoute("/lanes", streams.lanes),
        ReadRoute("/events/body/{key:path}", body),
        ReadRoute("/snapshot", snapshot),
    ]
