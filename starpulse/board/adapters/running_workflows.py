"""The tasks a Temporal workflow is running for: a claim whose task has one is alive without an Event.

A workflow waiting on CI emits no Event and no machine event for its task, so the claim TTL cannot see the session
that started it. Temporal's visibility API lists the running workflows whose id ends in the task id
(`task-lifecycle/TASK-N`)."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable

__all__ = ["DEFAULT_QUERY", "running_tasks"]

DEFAULT_QUERY = 'ExecutionStatus="Running"'
"""The visibility query `[board] workflows_query` defaults to: every running workflow of the namespace."""
_PAGE = 1000
_TIMEOUT = 10.0


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
        return json.load(resp)


def running_tasks(base_url: str, query: str = DEFAULT_QUERY, get: Callable[[str], dict] = _get) -> set[str]:
    """The lowercased task ids that name a workflow `query` matches on the Temporal server at `base_url`, such as
    `task-lifecycle/TASK-9918` as `task-9918`; raises OSError when the server cannot be read."""
    tasks: set[str] = set()
    token = ""
    while True:
        params = {"query": query, "maximumPageSize": _PAGE, **({"nextPageToken": token} if token else {})}
        page = get(f"{base_url.rstrip('/')}/api/v1/namespaces/default/workflows?{urllib.parse.urlencode(params)}")
        ids = (execution["execution"]["workflowId"] for execution in page.get("executions") or [])
        tasks.update(workflow_id.rpartition("/")[2].lower() for workflow_id in ids)
        token = page.get("nextPageToken") or ""
        if not token:
            return tasks
