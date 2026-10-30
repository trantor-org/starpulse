"""The capacity inputs the board feeds: the review load and the sessions held.

Both read the feed's open tasks (`BoardFeed.open_tasks`), so the sampler stays independent of the feed.
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


def sessions_held(tasks: Iterable[Mapping[str, Any]], working: str) -> int:
    """The sessions the Board says are running: each task in the `working` lane.

    A held task counts whether its session is mid-turn or idle on a wake (a PR's checks, a dependency), because the
    session stays a resident process either way. Counting only mid-turn sessions let a stalled downstream pile
    In Progress with no sessions use to stop new starts.
    """
    return sum(task["state"] == working for task in tasks)
