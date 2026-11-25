"""Where Grafana and Temporal post, off `/api` (it is the machines' receiver, not the page's API).

- `POST /intake/grafana`: the token-guarded push of a Grafana notice, saved in-process as one `alert-notice` event under `webhook_producer`; 404 where unset.
- `POST /intake/temporal-completion?workflow=<type>`: Temporal's completion callback for a workflow close, guarded by a producer token; 404 where unconfigured.
"""

from starlette.requests import Request
from starlette.responses import Response

from starpulse.runs.adapters.inbound.ingest import MAX_BATCH_BODY
from starpulse.runs.adapters.inbound.temporal_completion import completion
from starpulse.views.adapters.inbound.api.answering import seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import pushed, writing


def grafana(request: Request) -> Response | None:
    hook = seams(request).services.webhook
    return None if hook is None else pushed(request, "ingest", hook, MAX_BATCH_BODY)


def temporal_completion(request: Request) -> Response | None:
    events = seams(request).services.events
    if events is None:
        return None
    return pushed(
        request,
        "ingest",
        lambda auth, _raw: completion(events, auth, request.headers, request.query_params),
        MAX_BATCH_BODY,
    )


routes: list[ApiRoute] = [
    WriteRoute("/intake/grafana", ("POST",), writing(grafana)),
    WriteRoute("/intake/temporal-completion", ("POST",), writing(temporal_completion)),
]
