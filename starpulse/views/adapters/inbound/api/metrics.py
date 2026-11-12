"""`GET /metrics`: the Prometheus text of the gauges this process serves. It is no `/api` route: Prometheus scrapes the
path by its convention.

`GET /autopilot-log`: the autopilot's decision log as JSON, beside `/metrics` because a series per start would grow
without bound. It answers 404 on an instance that keeps no store for it.
"""

from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import Response

from starpulse.event_log import heartbeat
from starpulse.views.adapters.inbound.api.answering import answer, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute
from starpulse.views.adapters.outbound.gc_pauses import PAUSES
from starpulse.views.adapters.outbound.process_metrics import process_gauges


@reading
def prometheus(request: Request) -> Response:
    api = seams(request)
    services = api.services
    gauges = (
        services.actor_metrics,
        services.lane_metrics,
        services.conformance_metrics,
        services.lane_sweep_metrics,
        services.autopilot_metrics,
        services.sweeper_metrics,
        services.bridge_metrics,
        services.history_lag_metrics,
        api.snapshots.metrics,
        api.page_gauge,
    )
    text = "".join(gauge() for gauge in gauges if gauge) + process_gauges() + heartbeat.exposition() + PAUSES.exposition()
    return answer(request, text.encode(), content_type="text/plain; version=0.0.4; charset=utf-8")


@reading
def autopilot_log(request: Request) -> Response:
    read = seams(request).services.autopilot_log
    if read is None:
        return answer(request, b'{"error": "this instance keeps no autopilot log"}', 404)
    return answer(request, json.dumps(read()).encode())


routes: list[ApiRoute] = [ReadRoute("/metrics", prometheus), ReadRoute("/autopilot-log", autopilot_log)]
