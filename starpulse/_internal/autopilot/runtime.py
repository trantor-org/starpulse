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
from starpulse._internal.autopilot.quiet_hours import QuietHoursSetting
from starpulse._internal.autopilot.sampler import Crossing, Reading, Sampler
from starpulse._internal.autopilot.state import AutopilotState
from starpulse._internal.autopilot.toggle import TOGGLE_FILE, Toggle
from starpulse._internal.board.seam import Written
from starpulse._internal.config.autopilot import Autopilot
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.harness import HARNESS

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    toggle: Toggle
    sampler: Sampler
    quiet_hours: QuietHoursSetting
    loop: Loop | None = None
    _push_status: Callable[[], None] | None = None

    def set_enabled(self, value: bool) -> None:
        """Set the switch; turning it on wakes the loop, which admits what capacity allows without waiting for an event."""
        self.toggle.set(value)
        if value and self.loop is not None:
            self.loop.wake()
        self.push_status()

    def set_quiet_hours(self, raw: object) -> None:
        """Keep the window (None clears it); a window `parse` refuses raises ValueError. The loop wakes, since a window
        that no longer covers now may let a task in."""
        self.quiet_hours.set(raw)
        if self.loop is not None:
            self.loop.wake()
        self.push_status()

    def status(self) -> dict[str, Any]:
        """Whether admission is on, when capacity was last sampled, and each dimension's use against its limit.

        With a dispatch loop it also lists the sessions in flight and the next pick (null when none); without one the
        server has neither to say, so the keys are absent.
        """
        readings, at = self.sampler.readings()
        body: dict[str, Any] = {
            "enabled": self.toggle.get(),
            "quietHours": self.quiet_hours.state(),
            "sampledAt": at,
            "dimensions": [{"name": r.name, "use": r.use, "limit": r.limit} for r in readings],
        }
        if self.loop is not None:
            body["inFlight"] = self.loop.in_flight()
            body["next"] = self.loop.next_pick()
            if pauses := self.loop.pauses():
                body["pauses"] = pauses
        return body

    def push_status(self) -> None:
        """Tell the page stream the status now, when a `wire_status` publisher is bound."""
        if self._push_status is not None:
            self._push_status()

    def wire_status(self, publish: Callable[[str, dict[str, Any]], None]) -> None:
        """Push `status()` as an `autopilot` feed event after each sample, switch change and loop tick."""

        def push() -> None:
            publish("autopilot", self.status())

        self._push_status = push
        sample = self.sampler.sample

        def sampled() -> None:
            sample()
            push()

        self.sampler.sample = sampled  # type: ignore[method-assign]
        if self.loop is not None:
            tick = self.loop.tick

            def ticked(*args: Any, **kwargs: Any) -> list[str]:
                started = tick(*args, **kwargs)
                push()
                return started

            self.loop.tick = ticked  # type: ignore[method-assign]


def log_crossing(crossing: Crossing) -> None:
    state = "full" if crossing.full else "free"
    logger.info("StarPulse autopilot: %s is %s (%s of %s)", crossing.dimension, state, crossing.use, crossing.limit)


def build(
    policy: Autopilot,
    state_dir: Path,
    log: EventLog,
    feed: BoardFeed,
    probe: Callable[[], Mapping[str, float]] | None = None,
    on_crossing: Callable[[Crossing], object] = log_crossing,
    clock: Callable[[], float] = time.time,
    *,
    start: Callable[[str], str] | None = None,
    settle: Callable[[str, str], Written] | None = None,
    claim: Callable[[str, str], Written] | None = None,
    chain: Callable[[], Mapping[str, Mapping[str, Any]]] = dict,
    p_goals: Callable[[], Mapping[str, float]] = dict,
    lane: str = "",
) -> Runtime:
    """The switch kept in `log`'s store (a file in `state_dir` from before it moved there is imported once) and a sampler of `policy`'s limits over `feed`, on the local probe unless given another.

    With `start` and `settle` it also builds the dispatch loop over them, admitting from `lane` and keeping its run ledger
    beside the switch; a capacity crossing then wakes it. Without them there is only the switch and the sampler.
    """
    loop: Loop | None = None

    def crossed(crossing: Crossing) -> None:
        on_crossing(crossing)
        if loop is not None:
            loop.wake()

    state = AutopilotState(log)

    def remember_sample(readings: list[Reading], at: float) -> None:
        state.save_sample([{"name": r.name, "use": r.use, "limit": r.limit} for r in readings], at)

    sampler = Sampler(
        policy.limits,
        probe or LocalProbe(),
        sessions=lambda: sessions_in_flight(feed.machine_tasks(HARNESS.name)),
        review=lambda: review_points(feed.open_tasks(), policy.review_lane, policy.unsized_points),
        on_crossing=crossed,
        clock=clock,
        remember=remember_sample,
    )
    if saved := state.sample():
        try:
            rows, at = saved
            sampler.restore([Reading(str(row["name"]), float(row["use"]), float(row["limit"])) for row in rows], at)
        except KeyError, TypeError, ValueError:
            pass  # a malformed row is a missing sample; the first live pass is the baseline
    toggle = Toggle(log, state_dir / TOGGLE_FILE)
    quiet_hours = QuietHoursSetting(log)
    if start is not None and settle is not None:
        loop = Loop(
            feed=feed,
            policy=policy,
            toggle=toggle,
            sampler=sampler,
            ledger=Ledger(log, state_dir / LEDGER_FILE),
            start=start,
            settle=settle,
            chain=chain,
            p_goals=p_goals,
            lane=lane,
            claim=claim,
            clock=clock,
            quiet_hours=quiet_hours.get,
            log=log,
        )
    return Runtime(toggle, sampler, quiet_hours, loop)
