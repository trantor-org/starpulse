"""The analytics the page reads over the flow history and the sessions' telemetry.

- `GET /api/analytics/health`, `sessions`, `steps`, `transitions`, `cells`, `graph`, `stages`, `cost-to-go`, `diff`,
  `missed-loads` and `trace-clusters`: each filtered by the query.
"""

from __future__ import annotations

from collections.abc import Callable

from starlette.requests import Request
from starlette.responses import Response

from starpulse.contracts.analytics import Analytics
from starpulse.views.adapters.inbound.api.answering import answer, query, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, Endpoint, ReadRoute
from starpulse.views.ports.services import Services
from starpulse.views.application.queries.responses import (
    cells_response,
    cost_to_go_response,
    diff_response,
    graph_response,
    health_response,
    sessions_response,
    stages_response,
    steps_response,
    transitions_response,
)
from starpulse.views.application.queries.trace_responses import missed_loads_response, trace_clusters_response

_Respond = Callable[..., tuple[bytes, int]]


def _kept(request: Request, services: Services, compute: Callable[[], tuple[bytes, int]]) -> tuple[bytes, int]:
    """`compute`'s answer, or the kept answer to this query when the deployment keeps them (`Answers`)."""
    if services.answers is None:
        return compute()
    return services.answers.answer(f"{request.url.path}?{sorted(request.query_params.multi_items())}", compute)


@reading
def health(request: Request) -> Response:
    api = seams(request)
    return answer(request, *health_response(api.history, query(request), api.feed.machines, api.clock()))


def _sessions(respond: _Respond) -> Endpoint:
    @reading
    def endpoint(request: Request) -> Response:
        api = seams(request)
        services = api.services
        asked = query(request)
        return answer(
            request,
            *_kept(
                request,
                services,
                lambda: respond(services.telemetry, asked, api.feed.keys, api.clock(), services.analytics),
            ),
        )

    return endpoint


def _titled(respond: _Respond) -> Endpoint:
    @reading
    def endpoint(request: Request) -> Response:
        api = seams(request)
        services = api.services
        feed = api.feed
        asked = query(request)
        return answer(
            request,
            *_kept(
                request,
                services,
                lambda: respond(services.telemetry, asked, feed.keys, feed.titled, api.clock(), services.analytics),
            ),
        )

    return endpoint


def _ranked(respond: _Respond) -> Endpoint:
    @reading
    def endpoint(request: Request) -> Response:
        api = seams(request)
        services = api.services
        feed = api.feed
        asked = query(request)
        return answer(
            request,
            *_kept(
                request,
                services,
                lambda: respond(
                    services.telemetry, asked, feed.keys, feed.titled, services.analytics or Analytics(), api.clock()
                ),
            ),
        )

    return endpoint


routes: list[ApiRoute] = [
    ReadRoute("/analytics/health", health),
    ReadRoute("/analytics/sessions", _sessions(sessions_response)),
    ReadRoute("/analytics/steps", _sessions(steps_response)),
    ReadRoute("/analytics/transitions", _titled(transitions_response)),
    ReadRoute("/analytics/cells", _titled(cells_response)),
    ReadRoute("/analytics/graph", _titled(graph_response)),
    ReadRoute("/analytics/stages", _titled(stages_response)),
    ReadRoute("/analytics/cost-to-go", _titled(cost_to_go_response)),
    ReadRoute("/analytics/diff", _titled(diff_response)),
    ReadRoute("/analytics/missed-loads", _ranked(missed_loads_response)),
    ReadRoute("/analytics/trace-clusters", _ranked(trace_clusters_response)),
]
