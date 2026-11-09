"""The capacity inputs the board feeds: the review load and the sessions held.

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


def sessions_held(
    tasks: Iterable[Mapping[str, Any]],
    working: str,
    agents: Iterable[Mapping[str, Any]],
    now: float,
    stale_s: float = STALE_S,
) -> int:
    """The sessions the host runs: each task in the `working` lane, idle on a wake or mid-turn, and each task whose
    harness machine is `active` with an event within `stale_s`, in any lane.

    A held session is a resident process whether or not it is mid-turn, so a stalled downstream (CI, deliver) fills the
    sessions limit instead of piling up In Progress. It counts the operator's own sessions beside the scheduler's,
    because each takes the host's CPU and memory alike. A session killed mid-tool never gets its Stop, so its machine
    reads `active` until the history window drops it; the bound stops that session holding a slot.
    """
    held = {task["id"] for task in tasks if task["state"] == working}
    live = {agent["id"] for agent in agents if agent["state"] == "active" and now - agent["active"] <= stale_s}
    return len(held | live)
