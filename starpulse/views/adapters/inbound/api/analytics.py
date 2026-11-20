"""The analytics the page reads over the flow history and the sessions' telemetry.

- `GET /api/analytics/health`, `liveness`, `sessions`, `steps`, `transitions`, `spend`, `cells`, `estimates`, `graph`, `stages`, `cost-to-go`, `diff`,
  `missed-loads` and `trace-clusters`: each filtered by the query.
"""

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
    estimates_response,
    graph_response,
    health_response,
    liveness_response,
    refuses_at_once,
    sessions_response,
    spend_response,
    stages_response,
    steps_response,
    transitions_response,
)
from starpulse.views.application.queries.trace_responses import missed_loads_response, trace_clusters_response

_Respond = Callable[..., tuple[bytes, int]]


def _kept(
    request: Request,
    services: Services,
    asked: dict[str, list[str]],
    compute: Callable[[], tuple[bytes, int]],
    now: Callable[[], float],
    span: int = 1,
) -> tuple[bytes, int]:
    """`compute`'s answer, or the kept answer to this query when the deployment keeps them (`Answers`); a query that
    only refuses (`refuses_at_once`, the window `span` x `hours`) never waits behind a fold."""
    if services.answers is None:
        return compute()
    return services.answers.answer(
        request.url.path,
        str(sorted(request.query_params.multi_items())),
        compute,
        lambda: refuses_at_once(services.telemetry, asked, now(), span),
    )


@reading
def health(request: Request) -> Response:
    api = seams(request)
    return answer(request, *health_response(api.history, query(request), api.feed.machines, api.clock()))


@reading
def liveness(request: Request) -> Response:
    api = seams(request)
    feed = api.feed
    return answer(request, *liveness_response(api.history, query(request), feed.roles, feed.machines, api.clock()))


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
                asked,
                lambda: respond(services.telemetry, asked, api.feed.keys, api.clock(), services.analytics),
                api.clock,
            ),
        )

    return endpoint


def _titled(respond: _Respond, span: int = 1) -> Endpoint:
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
                asked,
                lambda: respond(services.telemetry, asked, feed.keys, feed.titled, api.clock(), services.analytics),
                api.clock,
                span,
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
                asked,
                lambda: respond(services.telemetry, asked, feed.titled, services.analytics or Analytics(), api.clock()),
                api.clock,
            ),
        )

    return endpoint


routes: list[ApiRoute] = [
    ReadRoute("/analytics/health", health, params=frozenset({"hours", "stuck_hours"})),
    ReadRoute("/analytics/liveness", liveness, params=frozenset({"hours", "stalled_minutes"})),
    ReadRoute("/analytics/sessions", _sessions(sessions_response), params=frozenset({"hours"})),
    ReadRoute("/analytics/steps", _sessions(steps_response), params=frozenset({"after", "hours", "limit"})),
    ReadRoute("/analytics/transitions", _titled(transitions_response), params=frozenset({"hours"})),
    ReadRoute("/analytics/spend", _titled(spend_response), params=frozenset({"hours"})),
    ReadRoute("/analytics/cells", _titled(cells_response), params=frozenset({"hours"})),
    ReadRoute("/analytics/estimates", _titled(estimates_response), params=frozenset({"hours", "milestone"})),
    ReadRoute("/analytics/graph", _titled(graph_response), params=frozenset({"hours"})),
    ReadRoute("/analytics/stages", _titled(stages_response, span=2), params=frozenset({"hours"})),
    ReadRoute("/analytics/cost-to-go", _titled(cost_to_go_response), params=frozenset({"hours"})),
    ReadRoute("/analytics/diff", _titled(diff_response), params=frozenset({"hours"})),
    ReadRoute("/analytics/missed-loads", _ranked(missed_loads_response), params=frozenset({"hours", "list", "skill"})),
    ReadRoute("/analytics/trace-clusters", _ranked(trace_clusters_response), params=frozenset({"hours", "min_sessions", "new_hours", "outliers", "threshold"})),
]
