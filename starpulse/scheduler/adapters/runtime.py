"""The scheduler's runtime: its switch, its capacity sampler and its dispatch loop, wired to the board and the harness events.

`build` assembles them from the `[scheduler]` policy; `Runtime.status` is what `GET /api/scheduler` answers and the
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

from starpulse.board.model.seam import Written
from starpulse.scheduler.model.config import Scheduler
from starpulse.board.board_feed import BoardFeed
from starpulse.scheduler.model.harness_setting import HarnessSetting
from starpulse.scheduler.model.inputs import review_points, sessions_in_flight
from starpulse.scheduler.model.ledger import Ledger
from starpulse.scheduler.adapters.loop import Loop
from starpulse.scheduler.adapters.probe import LocalProbe
from starpulse.scheduler.model.quiet_hours import QuietHoursSetting
from starpulse.scheduler.model.sampler import Crossing, Reading, Sampler
from starpulse.scheduler.model.state import SchedulerState
from starpulse.scheduler.model.toggle import Toggle
from starpulse.event_log.event_log import EventLog
from starpulse.harness_telemetry.harness import HARNESS

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    toggle: Toggle
    sampler: Sampler
    quiet_hours: QuietHoursSetting
    harness: HarnessSetting
    policy: Scheduler
    loop: Loop | None = None
    _push_status: Callable[[], None] | None = None
    _served: dict[str, Any] | None = None

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

    def set_harness(self, raw: object) -> None:
        """Keep the harness the loop starts on; a bad name raises ValueError. Wakes the loop so the next pick follows."""
        self.harness.set(raw)
        if self.loop is not None:
            self.loop.wake()
        self.push_status()

    def status(self) -> dict[str, Any]:
        """Whether admission is on, which harness it starts on, when capacity was last sampled, and each dimension.

        With a dispatch loop it also lists the sessions in flight, the next pick, per-harness session use and any
        credit pauses; without one those keys are absent.
        """
        readings, at = self.sampler.readings()
        selected = self.harness.get()
        dimensions = []
        for reading in readings:
            if reading.name == "sessions" and self.loop is not None:
                by = self.loop.sessions_by_harness()
                row = by.get(selected, {"use": 0.0, "limit": self.policy.session_limit(selected)})
                dimensions.append({"name": "sessions", "use": row["use"], "limit": row["limit"]})
            elif reading.name == "sessions":
                dimensions.append(
                    {"name": "sessions", "use": reading.use, "limit": self.policy.session_limit(selected)}
                )
            else:
                dimensions.append({"name": reading.name, "use": reading.use, "limit": reading.limit})
        body: dict[str, Any] = {
            "enabled": self.toggle.get(),
            "harness": selected,
            "quietHours": self.quiet_hours.state(),
            "sampledAt": at,
            "dimensions": dimensions,
        }
        if self.loop is not None:
            body["inFlight"] = self.loop.in_flight()
            body["next"] = self.loop.next_pick()
            body["sessionsByHarness"] = self.loop.sessions_by_harness()
            body["needsOperator"] = self.loop.needs_operator()
            if pauses := self.loop.pauses():
                body["pauses"] = pauses
        return body

    def served_status(self) -> dict[str, Any]:
        """The status the last push computed, which every change to what it shows pushes again: a `GET` reads it
        rather than deciding the next pick over the board for each request. Computed now before any push."""
        return self._served if self._served is not None else self.status()

    def push_status(self) -> None:
        """Tell the page stream the status now, when a `wire_status` publisher is bound."""
        if self._push_status is not None:
            self._push_status()

    def wire_status(self, publish: Callable[[str, dict[str, Any]], None]) -> None:
        """Push `status()` as an `scheduler` feed event after each sample, switch change and loop tick."""

        def push() -> None:
            self._served = self.status()
            publish("scheduler", self._served)

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
    logger.info("StarPulse scheduler: %s is %s (%s of %s)", crossing.dimension, state, crossing.use, crossing.limit)


def build(
    policy: Scheduler,
    log: EventLog,
    feed: BoardFeed,
    probe: Callable[[], Mapping[str, float]] | None = None,
    on_crossing: Callable[[Crossing], object] = log_crossing,
    clock: Callable[[], float] = time.time,
    *,
    start: Callable[..., str] | None = None,
    settle: Callable[[str, str], Written] | None = None,
    claim: Callable[[str, str], Written] | None = None,
    requeue: Callable[[str, str], Written] | None = None,
    merged: Callable[[Mapping[str, Any]], bool] = lambda agent: False,
    chain: Callable[[], Mapping[str, Mapping[str, Any]]] = dict,
    p_goals: Callable[[], Mapping[str, float]] = dict,
    lane: str = "",
) -> Runtime:
    """The switch kept in `log`'s store and a sampler of `policy`'s limits over `feed`, on the local probe unless given another.

    With `start` and `settle` it also builds the dispatch loop over them, admitting from `lane` and keeping its run ledger
    beside the switch; a capacity crossing then wakes it. Without them there is only the switch and the sampler.
    """
    loop: Loop | None = None

    def crossed(crossing: Crossing) -> None:
        on_crossing(crossing)
        if loop is not None:
            loop.wake()

    state = SchedulerState(log)

    def remember_sample(readings: list[Reading], at: float) -> None:
        state.save_sample([{"name": r.name, "use": r.use, "limit": r.limit} for r in readings], at)

    sampler = Sampler(
        policy.limits,
        probe or LocalProbe(),
        sessions=lambda: sessions_in_flight(feed.machine_tasks(HARNESS.name), clock()),
        review=lambda: review_points(feed.open_tasks(), policy.reviewed_lane(feed.roles.review), policy.unsized_points),
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
    toggle = Toggle(log)
    quiet_hours = QuietHoursSetting(log)
    harness = HarnessSetting(log)
    if start is not None and settle is not None:
        loop = Loop(
            feed=feed,
            policy=policy,
            toggle=toggle,
            sampler=sampler,
            ledger=Ledger(log),
            start=start,
            settle=settle,
            chain=chain,
            p_goals=p_goals,
            lane=lane,
            claim=claim,
            requeue=requeue,
            merged=merged,
            clock=clock,
            quiet_hours=quiet_hours.get,
            log=log,
            harness=harness,
        )
    return Runtime(toggle, sampler, quiet_hours, harness, policy, loop)
