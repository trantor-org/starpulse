"""Read-request durations as a Prometheus histogram, so the 50 ms p95 budget is observable from Prometheus.

`starpulse_request_duration_seconds{route,params}` holds the seconds each `/api` read took from arrival to the last byte
sent; `route` is the path template and `params` is `none` for an empty query string and `present` otherwise, never its
text, so the label set is the route table x 2 and never grows with the ids or filters requested.
"""

from prometheus_client import CollectorRegistry, Histogram, generate_latest

#: Dense around the 50 ms budget, so a p95 over it shows as a bucket and not a guess between two far edges.
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

_registry = CollectorRegistry()
_durations = Histogram(
    "starpulse_request_duration_seconds",
    "Seconds an /api read took from arrival to the last byte sent, by route template and whether it carried query params",
    ["route", "params"],
    buckets=BUCKETS,
    registry=_registry,
)


def observe(route: str, query_string: bytes, seconds: float) -> None:
    _durations.labels(route, "present" if query_string else "none").observe(seconds)


def exposition() -> str:
    return generate_latest(_registry).decode()
