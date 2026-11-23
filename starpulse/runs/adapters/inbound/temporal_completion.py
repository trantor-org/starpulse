"""The Temporal completion callback: `POST /api/temporal-completion?workflow=<type>`.

Temporal's server posts it once a workflow started with a `completion_callbacks` entry closes, retrying until the
ingest answers. The producer's bearer token rides the callback's own `Authorization` header; `Nexus-Operation-State`
(`succeeded`, `failed` or `canceled`) is the close and `Nexus-Link` names the workflow id and run id. The close lands
on `runs:events` as the run's `StepFinished` under the producer's name, its id the run id, so a retry appends nothing.
"""

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

if TYPE_CHECKING:  # annotation only
    from starpulse.runs.adapters.inbound.cloudevents import CloudEventsIngest

#: What each close state of the callback means as a run's status; Temporal reports a termination or timeout as `failed`.
STATES = {"succeeded": "succeeded", "failed": "failed", "canceled": "aborted"}
_LINK = re.compile(r"/workflows/(?P<workflow_id>.+)/(?P<run_id>[^/]+)/history")


def completion(
    events: CloudEventsIngest,
    authorization: str | None,
    headers: Mapping[str, str],
    query: Mapping[str, str],
) -> tuple[int, dict[str, Any]]:
    """Answer one callback: `(status, JSON body)`. `query` names the workflow type, which the callback does not carry."""
    if (name := events.owner(authorization)) is None:
        return 401, {"error": "a valid producer token is required: Authorization: Bearer <token>"}
    status = STATES.get(headers.get("Nexus-Operation-State", ""))
    link = _LINK.search(unquote(headers.get("Nexus-Link", "")))
    if status is None or link is None or not (workflow := query.get("workflow")):
        return 400, {"error": "a completion carries Nexus-Operation-State, Nexus-Link and ?workflow=<type>"}
    run_id = link["run_id"]
    event = {
        "specversion": "1.0",
        "id": run_id,
        "source": name,
        "type": "StepFinished",
        "subject": run_id,
        "data": {"workflow": workflow, "status": status},
    }
    return events.write(name, [event])
