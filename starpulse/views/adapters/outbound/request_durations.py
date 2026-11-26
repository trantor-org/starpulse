"""Read-request durations as a Prometheus histogram, so the 50 ms p95 budget is observable from Prometheus.

`starpulse_request_duration_seconds{route,params,shape,caller}` holds the seconds each `/api` read took from arrival to
the last byte sent. `route` is the path template; `params` is `none` for an empty query string and `present` otherwise;
`shape` is the sorted, comma-joined query names the route accepts, `none` with no query and `other` when any name is
outside them; `caller` is the `X-StarPulse-Client` header when it names a first-party client in `CALLERS`, else
`other`. No label ever carries a param's value or an unlisted name, so the set never grows with what clients send.

`/api/flows` is also read apart: `starpulse_flows_read_seconds{source}` holds the seconds the body took to make, `source`
being `rebuild` when the read fetched a body the writer stored anew and `cached` when it served the body an earlier read
fetched. Its reads per caller are the `caller` label of the histogram above.
"""

from urllib.parse import parse_qsl

from prometheus_client import CollectorRegistry, Histogram, generate_latest

#: Dense around the 50 ms budget, so a p95 over it shows as a bucket and not a guess between two far edges, and long
#: enough that a stalled read shows as its own tail and not as the top edge.
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120)

_registry = CollectorRegistry()
_durations = Histogram(
    "starpulse_request_duration_seconds",
    "Seconds an /api read took from arrival to the last byte sent, by route template, query shape, caller and, for `/graphql`, operation name",
    ["route", "params", "shape", "caller", "operation"],
    buckets=BUCKETS,
    registry=_registry,
)
_flows = Histogram(
    "starpulse_flows_read_seconds",
    "Seconds an /api/flows read took to make its body, by whether it fetched a newly stored body or served a cached one",
    ["source"],
    buckets=BUCKETS,
    registry=_registry,
)


#: The first-party clients that name themselves in `X-StarPulse-Client`; any other value reads `other`.
CALLERS = frozenset(
    {"web", "cli", "pull-request", "export", "delivery", "agent-commands", "ops-script", "probe"}
)


def _shape(accepted: frozenset[str], query_string: bytes) -> str:
    names = {name for name, _ in parse_qsl(query_string.decode("latin-1"), keep_blank_values=True)}
    if not names:
        return "none"
    return ",".join(sorted(names)) if names <= accepted else "other"


def observe(
    route: str, accepted: frozenset[str], query_string: bytes, client: str, seconds: float, operation: str = "none"
) -> None:
    """Observes one read of `route`, whose handler reads the query names `accepted`, sent by `client`; `operation` is the
    GraphQL operation a view declares or the schema fields the request selects, `other` when it selects none, and `none`
    for a read that is no GraphQL request."""
    caller = client if client in CALLERS else "other"
    params = "present" if query_string else "none"
    _durations.labels(route, params, _shape(accepted, query_string), caller, operation).observe(seconds)


def observe_flows(source: str, seconds: float) -> None:
    _flows.labels(source).observe(seconds)


def exposition() -> str:
    return generate_latest(_registry).decode()
