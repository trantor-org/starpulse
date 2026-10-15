"""The autopilot loop: admits Ready tasks into sessions as capacity allows, records each run and settles a stuck one.

It wakes on events, never on a dispatch timer: a task entering the eligible lane (or becoming workable there), a
session stopping, the toggle turning on, a capacity dimension crossing its limit (`wake`) and the feed's `autopilot`
status of a sample that leaves room for a task admission turned away. Each wake is one `tick`:

1. a run whose task left the eligible lane and In Progress is finished and written to the ledger (its outcome is the
   lane it went to, its duration and its resource peak); a session that stops while the task is still in those lanes is
   finished as `session-ended` and held out of admission until the task leaves them;
2. a session idle past `idle_minutes` with its task still open is settled to Needs attention once, with a reason, and is
   never started again;
3. while the switch is on and the clock is outside the quiet hours, `decide` ranks the Ready tasks and the loop starts the first admitted, then decides again over
   readings that carry that run's demand, until none is admitted.

A run holds its capacity from its start until its task leaves In Progress. While the harness has not yet seen its session
active the loop adds its demand to the sampler's readings itself; once it is active the sampler counts it. The one wake
a timer makes (`period`) only finishes and settles runs, so an idle session is found without any event arriving.

The runs in flight, each task's last start time and the last capacity sample live in the history store, so a restart
restores them. A start still inside `START_COOLDOWN` is not admitted again when that restore misses the run.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from starpulse._internal.autopilot.admission import Decision, decide, demand, tier_of
from starpulse._internal.autopilot.harness_setting import DEFAULT as DEFAULT_HARNESS
from starpulse._internal.autopilot.harness_setting import HarnessSetting
from starpulse._internal.autopilot.inputs import points
from starpulse._internal.autopilot.ledger import Ledger, RunRecord
from starpulse._internal.autopilot.quiet_hours import QuietHours
from starpulse._internal.autopilot.sampler import PERIOD, Reading, Sampler
from starpulse._internal.autopilot.state import START_COOLDOWN, AutopilotState
from starpulse._internal.autopilot.toggle import Toggle
from starpulse._internal.autopilot.usage_limit import until as usage_until
from starpulse._internal.board.seam import Written
from starpulse._internal.config.autopilot import Autopilot
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.harness import HARNESS
from starpulse.contracts.adapters import StartFailedError

logger = logging.getLogger(__name__)

IN_PROGRESS = "in_progress"
NEEDS_ATTENTION = "needs_attention"
SESSION_ENDED = "session-ended"
HELD_KEY = "autopilot.held"
PAUSES_KEY = "autopilot.harness_pauses"
#: The dimensions a host reading measures, so a run's peak is how far they rose while it ran.
_HOST = ("cpu", "memory")


def _run_from(fields: Mapping[str, Any]) -> _Run | None:
    """One saved run, or None when the row cannot be a `_Run`."""
    try:
        return _Run(
            str(fields["session"]),
            str(fields["tier"]),
            int(fields["points"]),
            float(fields["started_at"]),
            dict(fields["demand"]),
            dict(fields["baseline"]),
            dict(fields.get("peak") or {}),
            str(fields.get("harness") or DEFAULT_HARNESS),
        )
    except KeyError, TypeError, ValueError:
        return None


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
    harness: str = DEFAULT_HARNESS


class Loop:
    """Starts admitted tasks through `start` and settles stuck ones through `settle`.

    `start` takes a task id and answers the session's address, raising `StartFailedError` when it cannot; `settle` moves a
    task to Needs attention with the reason and says whether it did; `chain` is the trajectory chain `decide` ranks on
    and `p_goals` each task's forecast chance of the goal in `lane`.
    `lane` is the eligible lane, `claim` comments a started session's address on its task, `clock` is the loop's notion
    of now, `quiet_hours` answers the window in which it admits nothing, read on every pass so Admin's change holds, and
    `log` is the history store a restart restores in-flight runs and start times from.
    """

    def __init__(
        self,
        *,
        feed: BoardFeed,
        policy: Autopilot,
        toggle: Toggle,
        sampler: Sampler,
        ledger: Ledger,
        start: Callable[..., str],
        settle: Callable[[str, str], Written],
        chain: Callable[[], Mapping[str, Mapping[str, Any]]],
        lane: str,
        claim: Callable[[str, str], Written] | None = None,
        clock: Callable[[], float] = time.time,
        quiet_hours: Callable[[], QuietHours | None] = lambda: None,
        p_goals: Callable[[], Mapping[str, float]] = dict,
        log: EventLog | None = None,
        harness: HarnessSetting | None = None,
    ) -> None:
        self._feed = feed
        self._policy = policy
        self._toggle = toggle
        self._sampler = sampler
        self._ledger = ledger
        self._start = start
        self._settle = settle
        self._chain = chain
        self._p_goals = p_goals
        self._lane = lane
        self._claim = claim
        self._clock = clock
        self._quiet_hours = quiet_hours
        self._harness = harness
        self._state = AutopilotState(log) if log is not None else None
        self._running: dict[str, _Run] = {}
        self._starts: dict[str, float] = {}
        self._parked: dict[str, _Run] = {}
        self._held: set[str] = self._load_held()
        self._paused: dict[str, dict[str, Any]] = self._load_pauses()
        self._events: queue.Queue | None = None
        self._sampled_at: float | None = None  # the sample of the last `autopilot` status the loop was offered
        self._restore()

    def selected_harness(self) -> str:
        """The harness this loop starts on: the setting when one is wired, else Claude."""
        return self._harness.get() if self._harness is not None else DEFAULT_HARNESS

    def sessions_by_harness(self) -> dict[str, dict[str, float]]:
        """Each harness's in-flight count against its session cap, for the capacity strip's hint."""
        use: dict[str, float] = {}
        for run in self._running.values():
            use[run.harness] = use.get(run.harness, 0.0) + 1
        names = set(use) | set(self._policy.session_limits) | {self.selected_harness()}
        return {name: {"use": use.get(name, 0.0), "limit": self._policy.session_limit(name)} for name in sorted(names)}

    def wants(self, kind: str, data: Mapping[str, Any]) -> bool:
        """Whether a feed event (or a `wake`) can free or fill capacity: a task entering the eligible lane, a running task's
        own change, a harness session stopping, or the `autopilot` status of a new sample whose next pick would start.
        Every tool use is a harness move too, so only a stop counts. A tick publishes its status too, over the sample it
        ticked on, so a status wakes the loop once per sample: a start that keeps failing waits for the next sample."""
        if kind == "wake":
            return True
        if kind == "autopilot":
            fresh = data["sampledAt"] != self._sampled_at
            self._sampled_at = data["sampledAt"]
            return fresh and data["enabled"] and (data.get("next") or {}).get("verdict") == "starting"
        if kind == "task":
            agent = data["agent"]
            return data["id"] in self._running or (agent is not None and agent["state"] == self._lane)
        if kind == "move":
            if data["flow"] != HARNESS.name:
                return False
            if data["agent"]["state"] == "stopped":
                return True
            return data["id"] in self._held
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
        self._revive(now)
        self._release()
        self._reap(now)
        if not admit or not self._toggle.get() or self._quiet(now) or self._selected_paused(now):
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

    def _restore(self) -> None:
        """Load in-flight runs and start times the last process saved; a missing or unreadable row is an empty set."""
        if self._state is None:
            return
        for task, fields in self._state.inflight().items():
            if (run := _run_from(fields)) is not None:
                self._running[task] = run
        self._starts = self._state.starts()
        logger.info("StarPulse autopilot: restored %d in-flight", len(self._running))

    def _remember(self) -> None:
        """Write start times first so a crash before the in-flight row still leaves the cooldown."""
        if self._state is None:
            return
        now = self._clock()
        self._starts = {
            task: at for task, at in self._starts.items() if task in self._running or now - at < START_COOLDOWN
        }
        self._state.save_starts(self._starts)
        self._state.save_inflight({task: asdict(run) for task, run in self._running.items()})

    def _cooling(self, task: str, now: float) -> bool:
        started = self._starts.get(task)
        return started is not None and now - started < START_COOLDOWN

    def pauses(self) -> list[dict[str, Any]]:
        """Harnesses whose admission is paused until `until`, for `GET /api/autopilot`."""
        self._drop_expired(self._clock())
        return [
            {"harness": name, "until": row["until"], "reason": row["reason"]}
            for name, row in sorted(self._paused.items())
        ]

    def _quiet(self, now: float) -> bool:
        """Whether `now` is inside the quiet hours, when the loop admits nothing and finishes and settles runs as ever."""
        quiet = self._quiet_hours()
        return quiet is not None and quiet.contains(now)

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
        """Record each run whose task has left the eligible lane and In Progress, or whose session stopped with the task
        still there, and free its capacity."""
        for task, run in list(self._running.items()):
            agent = self._feed.task(task)
            state = agent["state"] if agent else None
            if state not in (self._lane, IN_PROGRESS):
                self._close(task, run, state or "closed", now)
                continue
            seen = self._feed.machine_task(HARNESS.name, task)
            if seen is not None and seen["state"] == "stopped":
                self._hold(task)
                self._close(task, run, SESSION_ENDED, now)

    def _close(self, task: str, run: _Run, outcome: str, now: float) -> None:
        del self._running[task]
        if outcome == SESSION_ENDED:
            self._parked[task] = run
        else:
            self._parked.pop(task, None)
        self._remember()
        record = RunRecord(
            task, run.tier, run.points, outcome, now - run.started_at, {**run.peak, "sessions": 1, "review": run.points}
        )
        try:
            self._ledger.record(record)
        except Exception:  # the store is a database: any failure to write must not stop the loop
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
        """The sampler's readings with the demand of each run the sampler does not yet count added; none without a sample.

        The sessions dimension is the selected harness only: its own in-flight count against its session cap.
        """
        readings, _ = self._sampler.readings()
        if not readings:
            self._sampler.sample()
            readings, _ = self._sampler.readings()
        taken: dict[str, float] = {}
        for task, run in self._running.items():
            if not self._counted(task):
                for name, need in run.demand.items():
                    if name == "sessions":
                        continue  # sessions is the selected harness's own count, below
                    taken[name] = taken.get(name, 0.0) + need
        harness = self.selected_harness()
        sessions_use = float(sum(1 for run in self._running.values() if run.harness == harness))
        sessions_limit = self._policy.session_limit(harness)
        out: list[Reading] = []
        for reading in readings:
            if reading.name == "sessions":
                out.append(replace(reading, use=sessions_use, limit=sessions_limit))
            else:
                out.append(replace(reading, use=reading.use + taken.get(reading.name, 0.0)))
        return out

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
        now = self._clock()
        cooling = {task for task in self._starts if self._cooling(task, now)}
        held = set(self._running) | skipped | cooling | self._held
        tasks = [{**agent, "workable": False} if agent["id"] in held else agent for agent in self._feed.open_tasks()]
        return tasks, decide(
            tasks, self._lane, readings, self._policy, self._chain(), self._ledger, log=log, p_goals=self._p_goals()
        )

    def next_pick(self) -> dict[str, Any] | None:
        """The task the next pass would start, or, when none fits, the top-ranked one and the dimension it waits on.

        Read for `GET /api/autopilot`, so it decides over the sampler's last reading without sampling and logs nothing;
        None before the first sample or with no workable task in the eligible lane. It does not depend on the switch; inside
        quiet hours the top task waits for them, whatever room the host has.
        """
        if not self._sampler.readings()[0]:
            return None
        tasks, decisions = self._decide(self._readings(), set(), log=False)
        if not decisions:
            return None
        top = decisions[0]  # the admitted in enforced order come first, then the refused by depth
        agent = next(a for a in tasks if a["id"] == top.task)
        now = self._clock()
        pause = self._selected_paused(now)
        waits = not top.admitted or self._quiet(now) or pause is not None
        if not top.admitted:
            reason = top.blocked_by
        elif self._quiet(now):
            reason = "quiet hours"
        elif pause is not None:
            reason = f"{pause} usage limit"
        else:
            reason = "goes next"
        return {
            "task": top.task,
            "title": agent["title"],
            "verdict": "waits" if waits else "starting",
            "reason": reason,
        }

    def _admit(self, now: float) -> list[str]:
        started: list[str] = []
        skipped: set[str] = set()  # a start that failed this pass, tried again on the next wake
        while readings := self._readings():
            tasks, decisions = self._decide(readings, skipped)
            if (picked := next((d for d in decisions if d.admitted), None)) is None:
                break
            agent = next(a for a in tasks if a["id"] == picked.task)
            harness = self.selected_harness()
            try:
                session = self._start(picked.task, harness=harness)
            except StartFailedError as exc:
                logger.warning("StarPulse autopilot: cannot start %s: %s", picked.task, exc)
                self._note_limit(str(exc), now, harness)
                if self._selected_paused(now):
                    break
                skipped.add(picked.task)
                continue
            self._starts[picked.task] = now
            self._running[picked.task] = _Run(
                session,
                tier_of(agent),
                points(agent["labels"], self._policy.unsized_points),
                now,
                picked.demand,
                self._use(),
                harness=harness,
            )
            self._remember()
            started.append(picked.task)
            logger.info("StarPulse autopilot: started %s at %s", picked.task, session)
            self._note_claim(picked.task, session)
        return started

    def _hold(self, task: str) -> None:
        self._held.add(task)
        self._save_held()

    def _revive(self, now: float) -> None:
        """A held task whose harness is active again is the same run, not a new admission."""
        revived = False
        for task in list(self._held):
            seen = self._feed.machine_task(HARNESS.name, task)
            if seen is None or seen["state"] != "active":
                continue
            self._held.discard(task)
            revived = True
            if task not in self._running:
                parked = self._parked.pop(task, None)
                self._running[task] = parked if parked is not None else self._stub(task, now)
        if revived:
            self._save_held()

    def _stub(self, task: str, now: float) -> _Run:
        agent = self._feed.task(task) or {"labels": (), "model": ""}
        return _Run(
            "",
            tier_of(agent),
            points(agent["labels"], self._policy.unsized_points),
            now,
            demand(agent, self._policy, self._ledger),
            self._use(),
            harness=self.selected_harness(),
        )

    def _release(self) -> None:
        """Drop a hold once the task leaves Ready and In Progress: a person or the sweep moved it."""
        kept = set()
        for task in self._held:
            agent = self._feed.task(task)
            if agent is not None and agent["state"] in (self._lane, IN_PROGRESS):
                kept.add(task)
        released = self._held - kept
        if not released:
            return
        for task in released:
            self._starts.pop(task, None)
            self._parked.pop(task, None)
        self._held = kept
        self._save_held()
        self._remember()

    def _note_limit(self, text: str, now: float, harness: str) -> None:
        resume = usage_until(text, now)
        if resume is None:
            return
        self._paused[harness] = {"until": resume, "reason": "usage limit"}
        self._save_pauses()

    def _selected_paused(self, now: float) -> str | None:
        """The selected harness when its credit pause is still live; other harnesses keep admitting."""
        self._drop_expired(now)
        harness = self.selected_harness()
        return harness if harness in self._paused else None

    def _drop_expired(self, now: float) -> None:
        live = {name: row for name, row in self._paused.items() if row["until"] > now}
        if live != self._paused:
            self._paused = live
            self._save_pauses()

    def _load_held(self) -> set[str]:
        raw = self._setting(HELD_KEY)
        if not isinstance(raw, list):
            return set()
        return {item for item in raw if isinstance(item, str)}

    def _load_pauses(self) -> dict[str, dict[str, Any]]:
        raw = self._setting(PAUSES_KEY)
        if not isinstance(raw, dict):
            return {}
        loaded: dict[str, dict[str, Any]] = {}
        for name, row in raw.items():
            if isinstance(name, str) and isinstance(row, dict) and isinstance(row.get("until"), (int, float)):
                loaded[name] = {"until": float(row["until"]), "reason": str(row.get("reason") or "usage limit")}
        return loaded

    def _save_held(self) -> None:
        self._put_setting(HELD_KEY, sorted(self._held))

    def _save_pauses(self) -> None:
        self._put_setting(PAUSES_KEY, self._paused)

    def _setting(self, key: str) -> Any:
        try:
            return self._ledger.log.setting(key)
        except Exception:  # an unreadable store holds nothing back
            logger.exception("StarPulse autopilot: cannot read %s", key)
            return None

    def _put_setting(self, key: str, value: Any) -> None:
        try:
            self._ledger.log.set_setting(key, value)
        except Exception:  # a failed write must not stop the loop
            logger.exception("StarPulse autopilot: cannot write %s", key)
