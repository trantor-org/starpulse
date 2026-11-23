"""Workflow runs.

- `POST /api/run/{name}`, `/api/runs/{instance}/{workflow}/rerun`: start a workflow, or run a finished one again.
"""

from typing import TYPE_CHECKING

from starlette.requests import Request

from starpulse.views.adapters.inbound.api.answering import client
from starpulse.views.adapters.inbound.api.table import ApiRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded
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

    return [
        WriteRoute("/run/{name:path}", ("POST",), guarded("run", run)),
        WriteRoute("/runs/{instance}/{workflow}/rerun", ("POST",), guarded("run", rerun)),
    ]
