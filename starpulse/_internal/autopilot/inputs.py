"""The capacity inputs the board and the harness events feed: the review load and the sessions in flight.

Both read the feed's agents (`BoardFeed.open_tasks`, `BoardFeed.machine_tasks("harness")`), so the sampler stays
independent of the feed.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

_SIZE = re.compile(r"size-(\d+)")


def points(labels: Iterable[str], unsized: int) -> int:
    """A task's points: its `size-N` label, else `unsized`."""
    return next((int(match[1]) for label in labels if (match := _SIZE.fullmatch(label))), unsized)


def review_points(tasks: Iterable[Mapping[str, Any]], lane: str, unsized: int) -> int:
    """The points of the Board tasks in `lane`, an unsized one counting `unsized`."""
    return sum(points(task["labels"], unsized) for task in tasks if task["state"] == lane)


def sessions_in_flight(agents: Iterable[Mapping[str, Any]]) -> int:
    """The harness sessions running now: each task whose harness machine is `active`.

    It counts every harness session on a task, the operator's own beside the autopilot's, because each takes the host's CPU
    and memory alike.
    """
    return sum(agent["state"] == "active" for agent in agents)
