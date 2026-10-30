"""`GET /metrics`: the Prometheus text of the gauges this process serves. It is no `/api` route: Prometheus scrapes the
path by its convention."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starpulse.views.adapters.inbound.api.neutral import ApiRoute, ReadRoute, Request, Response
from starpulse.views.adapters.outbound.process_metrics import process_gauges

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


def routes(api: Api) -> list[ApiRoute]:
    services = api.services
    gauges = (
        services.actor_metrics,
        services.lane_metrics,
        services.conformance_metrics,
        services.autopilot_metrics,
        api.snapshots.metrics,
        api.page_gauge,
    )
    metrics = tuple(gauge for gauge in gauges if gauge)

    def prometheus(request: Request) -> Response:
        text = "".join(metric() for metric in metrics) + process_gauges()
        return Response(text.encode(), content_type="text/plain; version=0.0.4; charset=utf-8")

    return [ReadRoute("/metrics", prometheus)]
