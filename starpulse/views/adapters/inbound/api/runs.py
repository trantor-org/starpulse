"""Workflow runs.

- `POST /api/run/{name}`, `/api/runs/{instance}/{workflow}/rerun`: start a workflow, or run a finished one again.
- `POST /api/machine-events`: the token-guarded push of machine events; 404 where a deployment leaves it unconfigured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.runs.ingest import MAX_BATCH_BODY
from starpulse.views.adapters.inbound.api.answering import client
from starpulse.views.adapters.inbound.api.table import ApiRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, pushed, writing
from starpulse.views.application.commands.runs import rerun_dag, run_dag

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


def routes(api: Api) -> list[ApiRoute]:
    feed, services = api.feed, api.services
    reruns = services.reruns or {}

    def run(request: Request) -> tuple[int, dict]:
        return run_dag(client(request), request.path_params["name"], services.starts, services.run_safe)

    def rerun(request: Request) -> tuple[int, dict]:
        name = f"{request.path_params['instance']}/{request.path_params['workflow']}"
        return rerun_dag(client(request), name, feed, reruns, services.run_safe)

    def machine_events(request: Request) -> Response | None:
        events = services.events
        if events is None:
            return None
        content_type = request.headers.get("Content-Type")
        return pushed(request, "ingest", lambda auth, raw: events(auth, content_type, raw), MAX_BATCH_BODY)

    return [
        WriteRoute("/run/{name:path}", ("POST",), guarded("run", run)),
        WriteRoute("/runs/{instance}/{workflow}/rerun", ("POST",), guarded("run", rerun)),
        WriteRoute("/machine-events", ("POST",), writing(machine_events)),
    ]
