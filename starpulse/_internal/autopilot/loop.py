"""The autopilot loop: admits Ready tasks into sessions as capacity allows, records each run and settles a stuck one.

It wakes on events, never on a dispatch timer: a task entering the eligible lane (or becoming workable there), a
session stopping, the toggle turning on and a capacity dimension crossing its limit (`wake`). Each wake is one `tick`:

1. a run whose task left the eligible lane and In Progress is finished and written to the ledger (its outcome is the
   lane it went to, its duration and its resource peak);
2. a session idle past `idle_minutes` with its task still open is settled to Needs attention once, with a reason, and is
   never started again;
3. while the switch is on, `decide` ranks the Ready tasks and the loop starts the first admitted, then decides again over
   readings that carry that run's demand, until none is admitted.

A run holds its capacity from its start until its task leaves In Progress. While the harness has not yet seen its session
active the loop adds its demand to the sampler's readings itself; once it is active the sampler counts it. The one wake
a timer makes (`period`) only finishes and settles runs, so an idle session is found without any event arriving.

The runs in flight are in memory: a restart forgets them, and a session started before it is then only counted, never
settled by this loop.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from starpulse._internal.autopilot.admission import Decision, decide, tier_of
from starpulse._internal.autopilot.inputs import points
from starpulse._internal.autopilot.ledger import Ledger, RunRecord
from starpulse._internal.autopilot.sampler import PERIOD, Reading, Sampler
from starpulse._internal.autopilot.toggle import Toggle
from starpulse._internal.board.seam import Written
from starpulse._internal.config.autopilot import Autopilot
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.harness import HARNESS
from starpulse.contracts.adapters import StartFailedError

logger = logging.getLogger(__name__)

IN_PROGRESS = "in_progress"
NEEDS_ATTENTION = "needs_attention"
#: The dimensions a host reading measures, so a run's peak is how far they rose while it ran.
_HOST = ("cpu", "memory")


@dataclass
class _Run:
    """One started session: its address, what it was admitted at, the host's load when it began and the most it has drawn."""

    session: str
    tier: str
    points: int
    started_at: float
    demand: Mapping[str, float]
    baseline: Mapping[str, float]
    peak: dict[str, float] = field(default_factory=dict)


class Loop:
    """Starts admitted tasks through `start` and settles stuck ones through `settle`.

    `start` takes a task id and answers the session's address, raising `StartFailedError` when it cannot; `settle` moves a
    task to Needs attention with the reason and says whether it did; `chain` is the trajectory chain `decide` ranks on.
    `lane` is the eligible lane, `claim` comments a started session's address on its task, and `clock` is the loop's
    notion of now.
    """

    def __init__(
        self,
        *,
        feed: BoardFeed,
        policy: Autopilot,
        toggle: Toggle,
        sampler: Sampler,
        ledger: Ledger,
        start: Callable[[str], str],
        settle: Callable[[str, str], Written],
        chain: Callable[[], Mapping[str, Mapping[str, Any]]],
        lane: str,
        claim: Callable[[str, str], Written] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._feed = feed
        self._policy = policy
        self._toggle = toggle
        self._sampler = sampler
        self._ledger = ledger
        self._start = start
        self._settle = settle
        self._chain = chain
        self._lane = lane
        self._claim = claim
        self._clock = clock
        self._running: dict[str, _Run] = {}
        self._events: queue.Queue | None = None

    def wants(self, kind: str, data: Mapping[str, Any]) -> bool:
        """Whether a feed event (or a `wake`) can free or fill capacity: a task entering the eligible lane, a running task's
        own change, or a harness session stopping. Every tool use is a harness move too, so only a stop counts."""
        if kind == "wake":
            return True
        if kind == "task":
            agent = data["agent"]
            return data["id"] in self._running or (agent is not None and agent["state"] == self._lane)
        if kind == "move":
            return data["flow"] == HARNESS.name and data["agent"]["state"] == "stopped"
        return False

    def wake(self) -> None:
        """Run a tick on the loop's thread: the toggle turned on, or a capacity dimension crossed its limit."""
        if self._events is not None:
            self._events.put(("wake", {}))

    def tick(self, admit: bool = True) -> list[str]:
        """Finish and settle runs, then (with `admit` and the switch on) start every task capacity allows; the ids started."""
        now = self._clock()
        self._observe()
        self._finish(now)
        self._reap(now)
        if not admit or not self._toggle.get():
            return []
        return self._admit(now)

    def run_forever(self, stop: threading.Event, period: float = PERIOD) -> None:
        """Tick on each wanted event until `stop` is set, and on `period` seconds without one to settle idle sessions."""
        self._feed.wait_replayed()
        _, events = self._feed.subscribe()
        self._events = events
        try:
            self._safely(self.tick)  # whatever waited before the loop began
            while not stop.is_set():
                try:
                    kind, data = events.get(timeout=period)
                except queue.Empty:
                    self._safely(self.tick, admit=False)
                    continue
                woken = self.wants(kind, data)
                while True:  # a burst of events is one tick
                    try:
                        kind, data = events.get_nowait()
                    except queue.Empty:
                        break
                    woken = self.wants(kind, data) or woken
                if woken:
                    self._safely(self.tick)
        finally:
            self._events = None
            self._feed.unsubscribe(events)

    def in_flight(self) -> list[dict[str, Any]]:
        """The sessions this loop started whose tasks are still running, oldest first, for `GET /api/autopilot`.

        Read from another thread than the loop's: `list(...)` takes one snapshot of the runs a tick may be changing.
        """
        sessions = []
        for task, run in list(self._running.items()):
            agent = self._feed.task(task)
            sessions.append(
                {
                    "task": task,
                    "title": agent["title"] if agent else task,
                    "model": (agent["model"] if agent else None) or "",
                    "started": run.started_at,
                    "url": run.session,
                }
            )
        return sessions

    def _safely(self, tick: Callable[..., object], **kwargs: Any) -> None:
        try:
            tick(**kwargs)
        except Exception:  # a failed pass is retried by the next event; it must not end the loop
            logger.exception("StarPulse autopilot: a pass failed")

    def _use(self) -> dict[str, float]:
        return {reading.name: reading.use for reading in self._sampler.readings()[0]}

    def _observe(self) -> None:
        """Raise each run's peak to how far the host's load now stands above where it began, shared among the runs."""
        use = self._use()
        for run in self._running.values():
            for name in _HOST:
                if name in use:
                    rise = max(0.0, use[name] - run.baseline.get(name, use[name])) / len(self._running)
                    run.peak[name] = max(run.peak.get(name, 0.0), rise)

    def _finish(self, now: float) -> None:
        """Record each run whose task has left the eligible lane and In Progress, and free its capacity."""
        for task, run in list(self._running.items()):
            agent = self._feed.task(task)
            state = agent["state"] if agent else None
            if state not in (self._lane, IN_PROGRESS):
                self._close(task, run, state or "closed", now)

    def _close(self, task: str, run: _Run, outcome: str, now: float) -> None:
        del self._running[task]
        record = RunRecord(task, run.tier, run.points, outcome, now - run.started_at, {**run.peak, "sessions": 1, "review": run.points})
        try:
            self._ledger.record(record)
        except OSError:
            logger.exception("StarPulse autopilot: cannot record the run of %s", task)

    def _reap(self, now: float) -> None:
        """Settle each run idle past the limit with its task still open: once, to Needs attention, never back to Ready."""
        limit = self._policy.idle_minutes * 60
        for task, run in list(self._running.items()):
            seen = self._feed.machine_task(HARNESS.name, task)
            idle = now - max(run.started_at, seen["active"] if seen else 0.0)
            if idle <= limit:
                continue
            reason = (
                f"Autopilot settled {task}: its session was idle for {idle / 60:.0f} minutes (limit "
                f"{self._policy.idle_minutes:g}) with the task still open. It is not started again."
            )
            if (written := self._settle(task, reason)).ok:
                self._close(task, run, NEEDS_ATTENTION, now)
            else:
                logger.warning("StarPulse autopilot: cannot settle %s: %s", task, written.output)

    def _counted(self, task: str) -> bool:
        """Whether the sampler already counts the task's session: its harness machine is active."""
        seen = self._feed.machine_task(HARNESS.name, task)
        return seen is not None and seen["state"] == "active"

    def _readings(self) -> list[Reading]:
        """The sampler's readings with the demand of each run the sampler does not yet count added; none without a sample."""
        readings, _ = self._sampler.readings()
        if not readings:
            self._sampler.sample()
            readings, _ = self._sampler.readings()
        taken: dict[str, float] = {}
        for task, run in self._running.items():
            if not self._counted(task):
                for name, need in run.demand.items():
                    taken[name] = taken.get(name, 0.0) + need
        return [replace(reading, use=reading.use + taken.get(reading.name, 0.0)) for reading in readings]

    def _note_claim(self, task: str, session: str) -> None:
        """Comment the session's address on its task; a board that refuses it leaves the session started."""
        if self._claim is None:
            return
        written = self._claim(task, f"Autopilot started {task}: {session}")
        if not written.ok:
            logger.warning("StarPulse autopilot: cannot comment the session of %s: %s", task, written.output)

    def _decide(
        self, readings: list[Reading], skipped: set[str], log: bool = True
    ) -> tuple[list[dict[str, Any]], list[Decision]]:
        """The open tasks with the running and `skipped` ones unworkable, and `decide`'s verdict on them over `readings`."""
        tasks = [
            {**agent, "workable": False} if agent["id"] in self._running or agent["id"] in skipped else agent
            for agent in self._feed.open_tasks()
        ]
        return tasks, decide(tasks, self._lane, readings, self._policy, self._chain(), self._ledger, log=log)

    def next_pick(self) -> dict[str, Any] | None:
        """The task the next pass would start, or, when none fits, the top-ranked one and the dimension it waits on.

        Read for `GET /api/autopilot`, so it decides over the sampler's last reading without sampling and logs nothing;
        None before the first sample or with no workable task in the eligible lane. It does not depend on the switch.
        """
        if not self._sampler.readings()[0]:
            return None
        tasks, decisions = self._decide(self._readings(), set(), log=False)
        if not decisions:
            return None
        top = decisions[0]  # the admitted in enforced order come first, then the refused by depth
        agent = next(a for a in tasks if a["id"] == top.task)
        return {
            "task": top.task,
            "title": agent["title"],
            "verdict": "starting" if top.admitted else "waits",
            "reason": "goes next" if top.admitted else top.blocked_by,
        }

    def _admit(self, now: float) -> list[str]:
        started: list[str] = []
        skipped: set[str] = set()  # a start that failed this pass, tried again on the next wake
        while readings := self._readings():
            tasks, decisions = self._decide(readings, skipped)
            if (picked := next((d for d in decisions if d.admitted), None)) is None:
                break
            agent = next(a for a in tasks if a["id"] == picked.task)
            try:
                session = self._start(picked.task)
            except StartFailedError as exc:
                logger.warning("StarPulse autopilot: cannot start %s: %s", picked.task, exc)
                skipped.add(picked.task)
                continue
            self._running[picked.task] = _Run(
                session,
                tier_of(agent),
                points(agent["labels"], self._policy.unsized_points),
                now,
                picked.demand,
                self._use(),
            )
            started.append(picked.task)
            logger.info("StarPulse autopilot: started %s at %s", picked.task, session)
            self._note_claim(picked.task, session)
        return started
