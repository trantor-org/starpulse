"""The commits that broke the default branch.

- `GET /api/breaking-changes`: each commit once with its detections, oldest first; `?open=1` keeps those with no postmortem.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, query, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute
from starpulse.views.application.queries.responses import breaking_changes_response

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def breaking_changes(request: Request) -> Response:
    return answer(request, *breaking_changes_response(seams(request).history, query(request)))


def routes(api: Api) -> list[ApiRoute]:
    return [ReadRoute("/breaking-changes", breaking_changes)]
