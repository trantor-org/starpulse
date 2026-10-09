"""The autopilot's runtime: its switch and its capacity sampler, wired to the board and the harness events.

`build` assembles them from the `[autopilot]` policy; `Runtime.status` is what `GET /api/autopilot` answers and the
capacity strip draws. Admission, ranking and dispatch subscribe to the sampler's crossings and read the switch.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starpulse._internal.autopilot.inputs import review_points, sessions_in_flight
from starpulse._internal.autopilot.probe import LocalProbe
from starpulse._internal.autopilot.sampler import Crossing, Sampler
from starpulse._internal.autopilot.toggle import Toggle
from starpulse._internal.config.autopilot import Autopilot
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.harness import HARNESS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Runtime:
    toggle: Toggle
    sampler: Sampler

    def status(self) -> dict[str, Any]:
        """Whether admission is on, when capacity was last sampled, and each dimension's use against its limit."""
        readings, at = self.sampler.readings()
        return {
            "enabled": self.toggle.get(),
            "sampledAt": at,
            "dimensions": [{"name": r.name, "use": r.use, "limit": r.limit} for r in readings],
        }


def log_crossing(crossing: Crossing) -> None:
    state = "full" if crossing.full else "free"
    logger.info("StarPulse autopilot: %s is %s (%s of %s)", crossing.dimension, state, crossing.use, crossing.limit)


def build(
    policy: Autopilot,
    toggle_path: Path,
    feed: BoardFeed,
    probe: Callable[[], Mapping[str, float]] | None = None,
    on_crossing: Callable[[Crossing], object] = log_crossing,
    clock: Callable[[], float] = time.time,
) -> Runtime:
    """The switch kept in `toggle_path` and a sampler of `policy`'s limits over `feed`, on the local probe unless given another."""
    sampler = Sampler(
        policy.limits,
        probe or LocalProbe(),
        sessions=lambda: sessions_in_flight(feed.machine_tasks(HARNESS.name)),
        review=lambda: review_points(feed.open_tasks(), policy.review_lane, policy.unsized_points),
        on_crossing=on_crossing,
        clock=clock,
    )
    return Runtime(Toggle(toggle_path), sampler)
