"""The analytics the page reads over the flow history and the sessions' telemetry.

- `GET /api/analytics/health`, `sessions`, `steps`, `transitions`, `cells`, `graph`, `stages`, `cost-to-go`, `diff`,
  `missed-loads` and `trace-clusters`: each filtered by the query.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from starpulse.contracts.analytics import Analytics
from starpulse.views.adapters.inbound.api.neutral import ApiRoute, Handler, ReadRoute, Request, Response
from starpulse.views.application.queries.responses import (
    cells_response,
    cost_to_go_response,
    diff_response,
    graph_response,
    health_response,
    missed_loads_response,
    sessions_response,
    stages_response,
    steps_response,
    trace_clusters_response,
    transitions_response,
)

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api

_Respond = Callable[..., tuple[bytes, int]]


def routes(api: Api) -> list[ApiRoute]:
    feed, services, clock = api.feed, api.services, api.clock
    telemetry, analytics = services.telemetry, services.analytics

    def health(request: Request) -> Response:
        return Response(*health_response(api.history, parse_qs(request.query), feed.machines, clock()))

    def sessions(respond: _Respond) -> Handler:
        return lambda request: Response(*respond(telemetry, parse_qs(request.query), feed.keys, clock(), analytics))

    def titled(respond: _Respond) -> Handler:
        return lambda request: Response(
            *respond(telemetry, parse_qs(request.query), feed.keys, feed.titled, clock(), analytics)
        )

    def ranked(respond: _Respond) -> Handler:
        return lambda request: Response(
            *respond(telemetry, parse_qs(request.query), feed.keys, feed.titled, analytics or Analytics(), clock())
        )

    return [
        ReadRoute("/analytics/health", health),
        ReadRoute("/analytics/sessions", sessions(sessions_response)),
        ReadRoute("/analytics/steps", sessions(steps_response)),
        ReadRoute("/analytics/transitions", titled(transitions_response)),
        ReadRoute("/analytics/cells", titled(cells_response)),
        ReadRoute("/analytics/graph", titled(graph_response)),
        ReadRoute("/analytics/stages", titled(stages_response)),
        ReadRoute("/analytics/cost-to-go", titled(cost_to_go_response)),
        ReadRoute("/analytics/diff", titled(diff_response)),
        ReadRoute("/analytics/missed-loads", ranked(missed_loads_response)),
        ReadRoute("/analytics/trace-clusters", ranked(trace_clusters_response)),
    ]
