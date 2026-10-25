"""The capacity inputs the board and the harness events feed: the review load and the sessions in flight.

Both read the feed's agents (`BoardFeed.open_tasks`, `BoardFeed.machine_tasks("harness")`), so the sampler stays
independent of the feed.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

_SIZE = re.compile(r"size-(\d+)")

# A tool call runs at most ten minutes before its TOOL_USED event; thrice that with no event is a dead session.
STALE_S = 1800.0


def points(labels: Iterable[str], unsized: int) -> int:
    """A task's points: its `size-N` label, else `unsized`."""
    return next((int(match[1]) for label in labels if (match := _SIZE.fullmatch(label))), unsized)


def review_points(tasks: Iterable[Mapping[str, Any]], lane: str | None, unsized: int) -> int:
    """The points of the Board tasks in `lane`, an unsized one counting `unsized`; no lane, no load."""
    return sum(points(task["labels"], unsized) for task in tasks if task["state"] == lane)


def sessions_in_flight(agents: Iterable[Mapping[str, Any]], now: float, stale_s: float = STALE_S) -> int:
    """The harness sessions running now: each task whose harness machine is `active` and had an event within `stale_s`.

    It counts every harness session on a task, the operator's own beside the scheduler's, because each takes the host's CPU
    and memory alike. A session killed mid-tool never gets its Stop, so its machine reads `active` until the history window
    drops it; the bound stops that session holding a slot.
    """
    return sum(agent["state"] == "active" and now - agent["active"] <= stale_s for agent in agents)
