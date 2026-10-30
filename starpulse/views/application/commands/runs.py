"""Start a run-safe workflow, or start it again."""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from typing import TYPE_CHECKING

from starpulse.board.board_feed import BoardFeed
from starpulse.contracts.adapters import StartFailedError
from starpulse.views.application.commands.guard import on_lan

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass

logger = logging.getLogger(__name__)


def run_dag(
    source: str, name: str, starts: Mapping[str, Callable[[str], str]], run_safe: Collection[str]
) -> tuple[int, dict[str, str]]:
    """Start the workflow `name` (`<instance>/<workflow>`) through its instance's `starts` entry, when there is one and
    `run_safe` holds it, for a browser at `source`: the HTTP status and JSON body to answer with."""
    if not on_lan(source):
        return 403, {"error": "Run now answers only loopback and private network (RFC 1918) browsers"}
    instance, _, workflow = name.partition("/")
    if (start := starts.get(instance)) is None:
        return 404, {"error": f"no adapter can start {name}"}
    if name not in run_safe:
        return 404, {"error": f"{name} is not declared run-safe"}
    try:
        return 200, {"runId": start(workflow)}
    except StartFailedError as exc:
        return 502, {"error": str(exc)}


def rerun_dag(
    source: str,
    name: str,
    feed: BoardFeed,
    reruns: Mapping[str, Callable[[str, Mapping[str, str]], str]],
    run_safe: Collection[str],
) -> tuple[int, dict[str, str]]:
    """Start the run-safe workflow `name` again with its force parameter set and the commit its newest unresolved
    failure applied, through its instance's `reruns` entry, for a browser at `source`: the HTTP status and JSON body.

    A forced failure clears only on a green forced run that covers it, so the rerun carries the failed run's own
    commit parameters (`after`, `before`, `task`) and nothing else it was given.
    """
    if not on_lan(source):
        return 403, {"error": "Rerun answers only loopback and private network (RFC 1918) browsers"}
    instance, _, workflow = name.partition("/")
    if (rerun := reruns.get(instance)) is None:
        return 404, {"error": f"no adapter can start {name}"}
    if name not in run_safe:
        return 404, {"error": f"{name} is not declared run-safe"}
    if (keys := feed.commit_keys(instance)) is None or not keys.force:
        return 409, {
            "error": f"{instance} declares no force parameter in [runs.commit]: a forced rerun is not possible"
        }
    if (failure := feed.open_failure(name)) is None:
        return 409, {"error": f"{name} has no unresolved failure"}
    carried = {key: failure["params"][key] for key in (keys.after, keys.before, keys.task) if key in failure["params"]}
    try:
        return 200, {"runId": rerun(workflow, {keys.force: "1", **carried})}
    except StartFailedError as exc:
        return 502, {"error": str(exc)}
