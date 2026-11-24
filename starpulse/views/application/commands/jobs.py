"""The jobs the runs adapters report: the list at a stream position, and one job."""

from collections.abc import Callable
from typing import Any

from starpulse.contracts.api.dto.requests import JobListRequest
from starpulse.views.application.commands.guard import with_request


@with_request(JobListRequest, "Listing jobs")
def jobs_list(
    request: JobListRequest, read: Callable[[], dict[str, Any]], position: Callable[[], int]
) -> tuple[int, dict[str, Any]]:
    """Every job and the error a runs instance reported, with the stream position read before them, so a subscription
    from it misses no change: the HTTP status and JSON body."""
    at = position()
    listed = read()
    return 200, {"position": at, "items": listed["dags"], "error": listed["error"]}


def job_record(read: Callable[[], dict[str, Any]], name: str) -> tuple[int, dict[str, Any]]:
    """The job `name` (`<instance>/<workflow>`) with its runner's start page: the HTTP status and JSON body."""
    if (job := next((dag for dag in read()["dags"] if dag["name"] == name), None)) is None:
        return 404, {"error": f"{name} is not a job here"}
    return 200, job
