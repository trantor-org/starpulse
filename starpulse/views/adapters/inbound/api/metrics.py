"""`GET /metrics`: the Prometheus text of the gauges this process serves. It is no `/api` route: Prometheus scrapes the
path by its convention.
"""

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute
from starpulse.views.adapters.outbound import request_durations
from starpulse.views.adapters.outbound.gc_pauses import PAUSES
from starpulse.views.adapters.outbound.process_metrics import process_gauges


@reading
def prometheus(request: Request) -> Response:
    api = seams(request)
    services = api.services
    gauges = (
        services.actor_metrics,
        services.lane_metrics,
        services.autopilot_metrics,
        services.storage_metrics,
        services.sweeper_metrics,
        services.bridge_metrics,
        services.completion_steps_metrics,
        services.history_lag_metrics,
        services.follower_lag_metrics,
        services.skill_cost_metrics,
        services.child_cpu_metrics,
        services.github_metrics,
        api.snapshots.metrics,
        api.page_gauge,
    )
    text = (
        "".join(gauge() for gauge in gauges if gauge)
        + process_gauges()
        + PAUSES.exposition()
        + request_durations.exposition()
    )
    return answer(request, text.encode(), content_type="text/plain; version=0.0.4; charset=utf-8")


routes: list[ApiRoute] = [
    ReadRoute("/metrics", prometheus),
]
