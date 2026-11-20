"""Read-request durations as a Prometheus histogram, so the 50 ms p95 budget is observable from Prometheus.

`starpulse_request_duration_seconds{route,params,shape,caller}` holds the seconds each `/api` read took from arrival to
the last byte sent. `route` is the path template; `params` is `none` for an empty query string and `present` otherwise;
`shape` is the sorted, comma-joined query names the route accepts, `none` with no query and `other` when any name is
outside them; `caller` is the `X-StarPulse-Client` header when it names a first-party client in `CALLERS`, else
`other`. No label ever carries a param's value or an unlisted name, so the set never grows with what clients send.
"""

from urllib.parse import parse_qsl

from prometheus_client import CollectorRegistry, Histogram, generate_latest

#: Dense around the 50 ms budget, so a p95 over it shows as a bucket and not a guess between two far edges.
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

_registry = CollectorRegistry()
_durations = Histogram(
    "starpulse_request_duration_seconds",
    "Seconds an /api read took from arrival to the last byte sent, by route template, query shape and caller",
    ["route", "params", "shape", "caller"],
    buckets=BUCKETS,
    registry=_registry,
)


#: The first-party clients that name themselves in `X-StarPulse-Client`; any other value reads `other`.
CALLERS = frozenset(
    {"web", "cli", "backlog", "pull-request", "export", "delivery", "dispatch", "agent-commands", "ops-script", "probe"}
)


def _shape(accepted: frozenset[str], query_string: bytes) -> str:
    names = {name for name, _ in parse_qsl(query_string.decode("latin-1"), keep_blank_values=True)}
    if not names:
        return "none"
    return ",".join(sorted(names)) if names <= accepted else "other"


def observe(route: str, accepted: frozenset[str], query_string: bytes, client: str, seconds: float) -> None:
    """Observes one read of `route`, whose handler reads the query names `accepted`, sent by `client`."""
    caller = client if client in CALLERS else "other"
    params = "present" if query_string else "none"
    _durations.labels(route, params, _shape(accepted, query_string), caller).observe(seconds)


def exposition() -> str:
    return generate_latest(_registry).decode()
