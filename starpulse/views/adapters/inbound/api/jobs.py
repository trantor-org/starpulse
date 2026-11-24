"""Jobs.

- `POST /api/jobs`: every workflow the runs adapters report, each with its runner's start page, and the stream position
  a `jobChanges` subscription follows from.
- `GET /api/jobs/{name}`: one workflow, `name` being `<instance>/<workflow>`.
"""

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole_body
from starpulse.views.application.commands.jobs import job_record, jobs_list
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def job(request: Request) -> Response:
    status, body = job_record(seams(request).feed.run_list, request.path_params["name"])
    return answer(request, encode("job", body), status)


def routes(api: Api) -> list[ApiRoute]:
    return [
        ReadRoute("/jobs/{name:path}", job),
        WriteRoute(
            "/jobs",
            ("POST",),
            guarded(
                "jobs",
                whole_body(lambda client, raw: jobs_list(client, raw, api.feed.run_list, api.snapshots.position)),
            ),
        ),
    ]
