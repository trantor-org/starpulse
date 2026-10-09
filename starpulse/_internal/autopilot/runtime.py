"""The autopilot's runtime: its switch, its capacity sampler and its dispatch loop, wired to the board and the harness events.

`build` assembles them from the `[autopilot]` policy; `Runtime.status` is what `GET /api/autopilot` answers and the
capacity strip draws. The loop (`loop.Loop`) admits, starts and settles; the sampler's crossings and the switch turning
on wake it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starpulse._internal.autopilot.inputs import review_points, sessions_in_flight
from starpulse._internal.autopilot.ledger import LEDGER_FILE, Ledger
from starpulse._internal.autopilot.loop import Loop
from starpulse._internal.autopilot.probe import LocalProbe
from starpulse._internal.autopilot.sampler import Crossing, Sampler
from starpulse._internal.autopilot.toggle import Toggle
from starpulse._internal.board.seam import Written
from starpulse._internal.config.autopilot import Autopilot
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.harness import HARNESS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Runtime:
    toggle: Toggle
    sampler: Sampler
    loop: Loop | None = None

    def set_enabled(self, value: bool) -> None:
        """Set the switch; turning it on wakes the loop, which admits what capacity allows without waiting for an event."""
        self.toggle.set(value)
        if value and self.loop is not None:
            self.loop.wake()

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
    *,
    start: Callable[[str], str] | None = None,
    settle: Callable[[str, str], Written] | None = None,
    claim: Callable[[str, str], Written] | None = None,
    chain: Callable[[], Mapping[str, Mapping[str, Any]]] = dict,
    lane: str = "",
) -> Runtime:
    """The switch kept in `toggle_path` and a sampler of `policy`'s limits over `feed`, on the local probe unless given another.

    With `start` and `settle` it also builds the dispatch loop over them, admitting from `lane` and keeping its run ledger
    beside the switch; a capacity crossing then wakes it. Without them there is only the switch and the sampler.
    """
    loop: Loop | None = None

    def crossed(crossing: Crossing) -> None:
        on_crossing(crossing)
        if loop is not None:
            loop.wake()

    sampler = Sampler(
        policy.limits,
        probe or LocalProbe(),
        sessions=lambda: sessions_in_flight(feed.machine_tasks(HARNESS.name)),
        review=lambda: review_points(feed.open_tasks(), policy.review_lane, policy.unsized_points),
        on_crossing=crossed,
        clock=clock,
    )
    toggle = Toggle(toggle_path)
    if start is not None and settle is not None:
        loop = Loop(
            feed=feed,
            policy=policy,
            toggle=toggle,
            sampler=sampler,
            ledger=Ledger(toggle_path.with_name(LEDGER_FILE)),
            start=start,
            settle=settle,
            chain=chain,
            lane=lane,
            claim=claim,
            clock=clock,
        )
    return Runtime(toggle, sampler, loop)
