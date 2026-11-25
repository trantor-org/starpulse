"""The scheduler loop: admits Ready tasks into sessions as capacity allows, and records each run.

It wakes on events, never on a dispatch timer: a task entering the eligible lane (or becoming workable there), a
session stopping, the toggle turning on, a capacity dimension crossing its limit (`wake`) and the feed's `scheduler`
status of a sample that leaves room for a task admission turned away. Each wake is one `tick`:

1. a run whose task left the eligible lane and In Progress is finished and written to the ledger (its outcome is the
   lane it went to, its duration and its resource peak); a session that stops while the task is still in those lanes is
   finished as `session-ended` and held out of admission until the task leaves them;
2. while the switch is on and the clock is outside the quiet hours, `decide` ranks the Ready tasks and the loop starts the first admitted, then decides again over
   readings that carry that run's demand, until none is admitted.

A run holds its capacity from its start until its task leaves In Progress, or, once the task was claimed, until it returns to a lane the loop admits from. While the harness has not yet seen its session
active the loop adds its demand to the sampler's readings itself; once it is active the sampler counts it. The one wake
a timer makes (`period`) only finishes runs.

The runs in flight, each task's last start time and the last capacity sample live in the history store, so a restart
restores them. A start still inside `START_COOLDOWN` is not admitted again when that restore misses the run.
"""

import logging
import queue
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.seam import Written
from starpulse.contracts.adapters import StartFailedError
from starpulse.event_log import start_requests
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.wake import StopEvent
from starpulse.harness_telemetry.model.harness import HARNESS
from starpulse.scheduler.model.admission import (
    REGRESSION,
    Decision,
    decide,
    demand,
    gate_verdicts,
    needs_operator,
    tier_of,
)
from starpulse.scheduler.model.changes import record
from starpulse.scheduler.model.config import Scheduler
from starpulse.scheduler.model.harness_setting import DEFAULT as DEFAULT_HARNESS
from starpulse.scheduler.model.harness_setting import HarnessSetting
from starpulse.scheduler.model.inputs import STALE_S, points
from starpulse.scheduler.model.ledger import Ledger, RunRecord
from starpulse.scheduler.model.quiet_hours import QuietHours
from starpulse.scheduler.model.sampler import Reading, Sampler
from starpulse.scheduler.model.start_failure import permanent, session_counts, sessions_full, transient
from starpulse.scheduler.model.state import START_COOLDOWN, SchedulerState
from starpulse.scheduler.model.toggle import Toggle
from starpulse.scheduler.model.usage_limit import until as usage_until

logger = logging.getLogger(__name__)

SESSION_ENDED = "session-ended"
SESSION_GONE = "session-gone"
HELD_KEY = "scheduler.held"
PAUSES_KEY = "scheduler.harness_pauses"
START_BACKOFF = 30.0
#: Seconds the loop waits for an event when it cannot read its deadlines, before it ticks and reads them again.
DEADLINE_RETRY = 30.0
BACKOFF_EXPONENT_MAX = 30  # START_BACKOFF * 2**30 is past the cap; a larger exponent overflows a float at 1024
#: Seconds a full session-start limit holds the whole queue back: it refuses every task alike, so no task is skipped alone.
#: The first refusal waits `START_BACKOFF`; each further one doubles it, up to this cap, and a start that lands resets it.
SESSIONS_FULL_BACKOFF_MAX = 5 * 60.0
#: Seconds admission for a harness halts after a start failure no retry can cure, before one start tries again.
START_HALT = 60 * 60.0
#: Admission verdicts counted so far, `{"admitted": n, "refused": n}`, kept in the worker state for `/metrics`.
TALLY_KEY = "scheduler.decisions"
#: The per-gate tally behind `starpulse_autopilot_gate_decisions_total`, keyed `<gate>/<verdict>`.
GATE_TALLY_KEY = "scheduler.gate_decisions"
#: The short ring of gate readings and block reasons kept in the worker state, newest last.
GATE_HISTORY_KEY = "scheduler.gate_history"
GATE_HISTORY_MAX = 100
#: How many of the newest rows `GET /api/admin` serves.
GATE_HISTORY_SERVED = 20
#: Seconds an unchanged block reason waits before the history keeps another row of readings.
GATE_HISTORY_EVERY = 300.0
#: The gate a full session-start service limit shows as, beside the capacity dimensions.
START_LIMIT = "start-limit"
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
            bool(fields.get("claimed", False)),
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
    claimed: bool = False  # the task was seen In Progress: a return to Ready means its session let go


class Loop:
    """Starts admitted tasks through `start`.

    `start` takes a task id and answers the session's address, raising `StartFailedError` when it cannot; `lane` is the
    eligible lane, `claim` comments a started session's address on its task, `merged` says whether a task's own pull
    request has merged, which leaves the task unstarted whatever its lane, `clock` is the loop's notion of now,
    `quiet_hours` answers the window in which it admits nothing, read on every pass so Admin's change holds, `log` is the
    history store a restart restores in-flight runs and start times from, and `transcript` answers when a session's
    transcript was last written, which lists a session the harness machine does not key to its task, and `end` ends a
    task's idle sessions, which a run gone without ever claiming its task needs because no lane entry ends it.
    """

    def __init__(
        self,
        *,
        feed: BoardFeed,
        policy: Scheduler,
        toggle: Toggle,
        sampler: Sampler,
        ledger: Ledger,
        start: Callable[..., str],
        lane: str,
        claim: Callable[[str, str], Written] | None = None,
        merged: Callable[[Mapping[str, Any]], bool] = lambda agent: False,
        clock: Callable[[], float] = time.time,
        quiet_hours: Callable[[], QuietHours | None] = lambda: None,
        room: Callable[[], bool] = lambda: True,
        log: EventLog | None = None,
        harness: HarnessSetting | None = None,
        transcript: Callable[[str], float | None] = lambda session: None,
        end: Callable[[str], None] = lambda task: None,
    ) -> None:
        self._feed = feed
        self._policy = policy
        self._toggle = toggle
        self._sampler = sampler
        self._ledger = ledger
        self._start = start
        self._lane = lane
        self._claim = claim
        self._merged = merged
        self._clock = clock
        self._quiet_hours = quiet_hours
        self._room = room
        self._harness = harness
        self._transcript = transcript
        self._end = end
        self._log = log
        self._state = SchedulerState(log) if log is not None else None
        self._running: dict[str, _Run] = {}
        self._starts: dict[str, float] = {}
        self._parked: dict[str, _Run] = {}
        self._granted: dict[str, tuple[float, Mapping[str, float]]] = {}
        self._held: set[str] = self._load_held()
        self._paused: dict[str, dict[str, Any]] = self._load_pauses()
        self._skip_logged: str | None = None  # the last reason a tick logged for skipping admission
        self._full: tuple[int, float] = (0, 0.0)  # refusals while the session limit is full, and when to try again
        self._full_counts: tuple[int, int] = (0, 0)  # the live count and limit the last refusal named
        self._events: queue.Queue | None = None
        self._refusals_logged: dict[str, str | None] = {}  # the Ready tasks whose refusal is already logged, with its cause
        self._blocked = False  # the last pass was refused for capacity: only a capacity event retries it
        self._refused = False  # a resume or nudge want the last grant pass left pending for headroom: the next fresh sample retries it
        self._sampled_at: float | None = None  # the sample of the last `scheduler` status the loop was offered
        self._restore()

    def selected_harness(self) -> str:
        """The harness this loop starts on: the setting when one is wired, else Claude."""
        return self._harness.get() if self._harness is not None else DEFAULT_HARNESS

    def sessions_by_harness(self) -> dict[str, dict[str, float]]:
        """Each harness's in-flight count against its session cap, for the capacity strip's hint."""
        use = self._sessions_used()
        names = set(use) | set(self._policy.session_limits) | {self.selected_harness()}
        return {name: {"use": use.get(name, 0.0), "limit": self._policy.session_limit(name)} for name in sorted(names)}

    def _sessions_used(self) -> dict[str, float]:
        """Sessions per harness: the loop's runs that are at work, and each task held In Progress outside them, counted on
        the default harness because the harness machine does not say which harness opened it."""
        use: dict[str, float] = {}
        now = self._clock()
        agents = self._open_agents()
        for task, run in list(self._running.items()):
            if self._at_work(task, run, agents, now):
                use[run.harness] = use.get(run.harness, 0.0) + 1
        if outside := len(self._held_outside()):
            use[DEFAULT_HARNESS] = use.get(DEFAULT_HARNESS, 0.0) + outside
        return use

    def _at_work(self, task: str, run: _Run, agents: Mapping[str, Mapping[str, Any]], now: float) -> bool:
        """Whether a run's session holds a slot: its task is held In Progress, or still in the eligible lane with its start
        or last harness event inside `STALE_S`. A task in any other lane holds none: its session is reaped or about to be.
        A run whose task was claimed then returned to the eligible lane holds none either: its session let the task go.
        A session at a prompt that never claimed its task is a resident process doing no work."""
        state = agents[task]["state"] if task in agents else None
        if state == self._feed.roles.working:
            run.claimed = True
            return True
        if state not in self._lanes() or run.claimed:
            return False
        seen = self._feed.machine_task(HARNESS.name, task)
        return now - max(run.started_at, seen["active"] if seen else 0.0) <= STALE_S

    def _gone(self, task: str, run: _Run, agents: Mapping[str, Mapping[str, Any]], now: float) -> bool:
        """Whether a run's task sits in a lane the loop admits from and its session has made no move inside `STALE_S`: the
        session ended without a Stop, so the run is no longer in flight and the task is Ready work again."""
        agent = agents.get(task)
        return agent is not None and agent["state"] in self._lanes() and not self._at_work(task, run, agents, now)

    def _held_outside(self) -> set[str]:
        """The In Progress tasks `_running` does not hold that a session holds, idle on a wake or mid-turn: an idle session
        is still a resident process, so a stalled downstream fills the sessions cap instead of piling up In Progress. A
        task sent back with no live session is Ready work (`_candidate`), not a held one."""
        live = self._live()
        working = self._feed.roles.working
        return {
            agent["id"]
            for agent in self._feed.open_tasks()
            if agent["state"] == working
            and agent["id"] not in self._running
            and (agent["id"] in live or REGRESSION not in agent["labels"])
        }

    def _outside(self, states: tuple[str, ...] = ("active", "stopped")) -> dict[str, dict[str, Any]]:
        """The In Progress tasks a live session holds that `_running` does not: one `POST /api/start` or the operator opened.

        A session is live when its harness machine is in `states` with an event inside `STALE_S`. `stopped` is
        live too: every mid-turn reply sets it until the next tool result, so a session running a tool or waiting on the
        model is `stopped` most of the time.
        """
        now = self._clock()
        found = {}
        for agent in self._feed.open_tasks():
            task = agent["id"]
            if agent["state"] != self._feed.roles.working or task in self._running:
                continue
            seen = self._feed.machine_task(HARNESS.name, task)
            if seen is not None and seen["state"] in states and now - seen["active"] <= STALE_S:
                found[task] = {"agent": agent, "seen": seen}
        return found

    def _transcribed(self, seen: Mapping[str, Any]) -> dict[str, tuple[dict[str, Any], float]]:
        """The In Progress tasks neither `_running` nor `seen` holds whose assignee session wrote its transcript inside
        `STALE_S`: a session the harness machine keys to the branch it opened on, not the task it claimed since."""
        now = self._clock()
        found = {}
        for agent in self._feed.open_tasks():
            task = agent["id"]
            if agent["state"] != self._feed.roles.working or task in self._running or task in seen:
                continue
            written = self._transcript(agent.get("assignee") or "")
            if written is not None and now - written <= STALE_S:
                found[task] = (agent, written)
        return found

    def wants(self, kind: str, data: Mapping[str, Any]) -> bool:
        """Whether a feed event (or a `wake`) can free or fill capacity: a task entering the eligible lane, a running task's
        own change, a harness session stopping, or the `scheduler` status of a new sample whose next pick would start or while a
        resume or nudge want waits for room.
        Every tool use is a harness move too, so only a stop counts. A tick publishes its status too, over the sample it
        ticked on, so a status wakes the loop once per sample: a start that keeps failing waits for the next sample."""
        if kind == "wake":
            return self._capacity_event()
        if kind == "scheduler":
            fresh = data["sampledAt"] != self._sampled_at
            self._sampled_at = data["sampledAt"]
            return fresh and (self._refused or data["enabled"] and (data.get("next") or {}).get("verdict") == "starting")
        if kind == "task":
            if data["id"] in self._running:
                return not self._blocked or self._leaves(data["agent"]) and self._capacity_event()
            agent = data["agent"]
            return not self._blocked and agent is not None and self._may_enter(agent)
        if kind == "move":
            if data["machine"] != HARNESS.name:
                return False
            if data["agent"]["state"] == "stopped" or data["id"] in self._held:
                return self._capacity_event()
        return False

    def _leaves(self, agent: Mapping[str, Any] | None) -> bool:
        """Whether a running task's change takes it out of the eligible lanes and In Progress, which frees its slot."""
        return agent is None or agent["state"] not in (*self._lanes(), self._feed.roles.working)

    def _capacity_event(self) -> bool:
        """A pressure crossing, a session ending or a run's own change: the one kind of event that retries a capacity refusal."""
        self._blocked = False
        return True

    def _lanes(self) -> tuple[str, ...]:
        """The lanes a session admits a task from: the eligible lane, then the verify lane when one is configured."""
        verify = self._policy.verify_lane
        return (self._lane, verify) if verify else (self._lane,)

    def _may_enter(self, agent: Mapping[str, Any]) -> bool:
        """Whether the task is in an admitted lane, or In Progress with the `regression` label a verify miss sets."""
        if agent["state"] in self._lanes():
            return True
        return agent["state"] == self._feed.roles.working and REGRESSION in agent.get("labels", ())

    def wake(self) -> None:
        """Run a tick on the loop's thread: the toggle turned on, or a capacity dimension crossed its limit."""
        if self._events is not None:
            self._events.put(("wake", {}))

    def tick(self, admit: bool = True) -> list[str]:
        """Finish and settle runs, then (with `admit` and the switch on) start every task capacity allows; the ids started."""
        now = self._clock()
        agents = self._open_agents()
        self._observe()
        self._finish(now, agents)
        self._revive(now, agents)
        self._release(now, agents)
        if not admit:
            return []
        self._grant()
        if (why := self._admission_off(now)) is not None:
            if why != self._skip_logged:
                logger.info("StarPulse scheduler: admission skipped: %s", why)
            self._skip_logged = why
            return []
        self._skip_logged = None
        return self._admit(now)

    def _grant(self) -> None:
        """Admit the resumes and nudges the task actor wants, each while the room left fits what it draws. A start
        admitted stays admitted until its want changes; a refused one waits for the next capacity event. The switch and
        quiet hours gate dispatch, not a session the task already holds, so they do not apply."""
        if self._log is None:
            return
        open_tasks = self._feed.open_tasks()
        working = {agent["id"]: agent for agent in open_tasks if agent["state"] == self._feed.roles.working}
        asked = {task: row for task, row in start_requests.wanted(self._log).items() if task in working}
        grants = {task: at for task, at in start_requests.admitted(self._log).items() if asked.get(task, {}).get("at") == at}
        pending = set(asked) - set(grants)
        rows = [{**agent, "workable": True} if task in pending else agent for task, agent in working.items()]
        others = [agent for agent in open_tasks if agent["id"] not in working]
        self._granted = {
            task: grant
            for task, grant in self._granted.items()
            if task in working and not self._counted(task) and asked.get(task, {}).get("at") in (None, grant[0])
        }
        readings = self.readings() if pending else []
        while pending:
            decisions = decide([*others, *rows], self._lane, readings, self._policy, self._ledger, log=False, starting={task: asked[task]["at"] for task in pending})
            if (picked := next((d for d in decisions if d.admitted and d.task in pending), None)) is None:
                break
            pending.discard(picked.task)
            grants[picked.task] = asked[picked.task]["at"]
            self._granted[picked.task] = (asked[picked.task]["at"], picked.demand)
            readings = [replace(r, use=r.use + picked.demand[r.name]) for r in readings]
        start_requests.admit(self._log, grants)
        self._refused = bool(pending)

    def _admission_off(self, now: float) -> str | None:
        """Why this tick admits nothing, or None; a gated-off tick logs no per-task decision, so this names the gate."""
        if not self._toggle.get():
            return "the switch is off"
        if self._quiet(now):
            return "inside quiet hours"
        if paused := self._selected_paused(now):
            return f"{paused} is paused"
        if not self._room():
            return "no account has room"
        return None

    def run_forever(self, stop: StopEvent) -> None:
        """Tick on each wanted event until `stop` is set, and when a deadline falls due: a start backoff or a
        credit pause ending. A capacity event samples first, so the session and review counts follow the event."""
        self._feed.wait_replayed()
        events = self._feed.follow_changes()
        self._events = events
        try:
            self._safely(self.tick)  # whatever waited before the loop began
            while not stop.is_set():
                try:
                    kind, data = events.get(timeout=self._wait())
                except queue.Empty:
                    self._safely(self.tick)
                    continue
                woken = self.wants(kind, data)
                while True:  # a burst of events is one tick
                    try:
                        kind, data = events.get_nowait()
                    except queue.Empty:
                        break
                    woken = self.wants(kind, data) or woken
                if woken:
                    self._safely(self._sampler.sample)
                    self._safely(self.tick)
        finally:
            self._events = None
            self._feed.unsubscribe(events)

    def _wait(self) -> float | None:
        try:
            return self._next_due(self._clock())
        except Exception:  # a failed read of the deadlines is retried on the next wait; it must not end the loop
            logger.exception("StarPulse scheduler: reading the next deadline failed")
            return DEADLINE_RETRY

    def _next_due(self, now: float) -> float | None:
        """Seconds to the earliest deadline the loop must wake for with no event, or None: the end of a
        sessions-full wait, a credit pause, or a started session's `STALE_S` without a move
        (`_gone` closes its run on that tick; a tool use is no wanted event, so a session that died unclaimed wakes none).
        A move since the deadline was read only makes that tick find the run still at work, and the next call re-reads.
        A stale deadline that fell between two calls is due now when `_gone` would close its run, so the tick is not lost."""
        due = [self._full[1]] if self._full[1] > now else []
        due += [row["until"] for row in self._paused.values() if row["until"] > now]
        for task, run in list(self._running.items()):
            if not run.claimed:
                seen = self._feed.machine_task(HARNESS.name, task)
                stale = max(run.started_at, seen["active"] if seen else 0.0) + STALE_S + 1
                if stale > now:
                    due.append(stale)
                elif self._gone(task, run, self._open_agents(), now):
                    due.append(now)
        return max(0.0, min(due) - now) if due else None

    def needs_operator(self) -> list[dict[str, str]]:
        """The tasks in the eligible lane that ask the operator for a decision, which admission never starts."""
        tasks = self._feed.open_tasks()
        return [{"task": t["id"], "title": t["title"]} for t in tasks if t["state"] == self._lane and needs_operator(t)]

    def in_flight(self) -> list[dict[str, Any]]:
        """Every live session holding an In Progress task, oldest first, for `GET /api/admin`: the loop's runs, its
        stopped runs the sessions cap still counts (`_held_outside`, whatever their age), and the sessions it did not track (a stopped one included, within `STALE_S` of its last event), whose address is unknown (`url` is empty) and whose start is the harness machine's
        first move on the task, and the assignee sessions that wrote a transcript inside `STALE_S` with no harness machine row
        on the task, started when the task entered In Progress.

        Read from another thread than the loop's: `list(...)` takes one snapshot of the runs a tick may be changing.
        """
        sessions = []
        agents = self._open_agents()
        counted = self._held_outside()
        held = {task: run for task, run in list(self._parked.items()) if task in counted}
        for task, run in [*list(self._running.items()), *held.items()]:
            agent = agents.get(task)
            sessions.append(
                {
                    "task": task,
                    "title": agent["title"] if agent else task,
                    "model": (agent["model"] if agent else None) or "",
                    "started": run.started_at,
                    "url": run.session,
                }
            )
        outside = {task: found for task, found in self._outside().items() if task not in held}
        for task, found in outside.items():
            agent, seen = found["agent"], found["seen"]
            sessions.append(
                {
                    "task": task,
                    "title": agent["title"],
                    "model": agent["model"] or "",
                    "started": seen["trail"][0]["at"] if seen["trail"] else seen["active"],
                    "url": "",
                }
            )
        for task, (agent, written) in self._transcribed({**outside, **held}).items():
            sessions.append(
                {
                    "task": task,
                    "title": agent["title"],
                    "model": agent["model"] or "",
                    "started": agent["entered"] or written,
                    "url": "",
                }
            )
        return sorted(sessions, key=lambda session: session["started"])

    def _restore(self) -> None:
        """Load the in-flight runs, a stopped one marked, and the start times the last process saved; a missing or unreadable
        row is an empty set."""
        if self._state is None:
            return
        now = self._clock()
        agents = self._open_agents()
        for task, fields in self._state.inflight().items():
            run = _run_from(fields)
            if run is not None and (fields.get("stopped") or not self._gone(task, run, agents, now)):
                (self._parked if fields.get("stopped") else self._running)[task] = run
        self._starts = self._state.starts()
        names = sorted({*self._running, *self._parked})
        logger.info("StarPulse scheduler: restored %d in-flight: %s", len(names), ", ".join(names) or "none")

    def _remember(self) -> None:
        """Write start times first so a crash before the in-flight row still leaves the cooldown."""
        if self._state is None:
            return
        now = self._clock()
        self._starts = {
            task: at for task, at in self._starts.items() if task in self._running or now - at < START_COOLDOWN
        }
        self._state.save_starts(self._starts)
        self._state.save_inflight(
            {
                **{task: asdict(run) for task, run in self._running.items()},
                **{task: {**asdict(run), "stopped": True} for task, run in self._parked.items()},
            }
        )

    def _cooling(self, task: str, now: float) -> bool:
        started = self._starts.get(task)
        return started is not None and now - started < START_COOLDOWN

    def pauses(self) -> list[dict[str, Any]]:
        """Harnesses whose admission is paused until `until`, for `GET /api/admin`."""
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
            logger.exception("StarPulse scheduler: a pass failed")

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

    def _open_agents(self) -> dict[str, dict[str, Any]]:
        """Every open task by id: one read, where `feed.task` is a read-model query for each task asked of it."""
        return {agent["id"]: agent for agent in self._feed.open_tasks()}

    def _finish(self, now: float, agents: Mapping[str, Mapping[str, Any]]) -> None:
        """Record each run whose task has left the eligible lane and In Progress, or whose session stopped with the task
        still there, and free its capacity."""
        for task, run in list(self._running.items()):
            agent = agents.get(task)
            state = agent["state"] if agent else None
            phase = self._feed.machine_task("in-progress", task)
            if phase and phase["state"] == "parked":  # a parked phase waits whatever lane the board still holds
                state = "waiting"
            if state not in (*self._lanes(), self._feed.roles.working):
                self._close(task, run, state or "closed", now)
                continue
            if self._gone(task, run, agents, now):
                if not run.claimed:
                    self._end(task)
                self._close(task, run, SESSION_GONE, now)
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
            logger.exception("StarPulse scheduler: cannot record the run of %s", task)

    def _counted(self, task: str) -> bool:
        """Whether the sampler already counts the task's session: its harness machine is active."""
        seen = self._feed.machine_task(HARNESS.name, task)
        return seen is not None and seen["state"] == "active"

    def readings(self) -> list[Reading]:
        """The sampler's readings with the demand of each run the sampler does not yet count added; none without a sample.

        The sessions dimension is the selected harness only: its own in-flight count against its session cap.
        """
        readings, _ = self._sampler.readings()
        if not readings:
            self._sampler.sample()
            readings, _ = self._sampler.readings()
        taken: dict[str, float] = {}
        # A grant stays reserved after the task actor dispatches it, until the sampler counts the session or the task leaves work.
        held = {**{task: demand for task, (_, demand) in self._granted.items()}, **{task: run.demand for task, run in list(self._running.items())}}  # the loop thread changes both
        for task, needs in held.items():
            if not self._counted(task):
                for name, need in needs.items():
                    if name == "sessions":
                        continue  # sessions is the selected harness's own count, below
                    taken[name] = taken.get(name, 0.0) + need
        harness = self.selected_harness()
        sessions_use = self._sessions_used().get(harness, 0.0)
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
        written = self._claim(task, f"Scheduler started {task}: {session}")
        if not written.ok:
            logger.warning("StarPulse scheduler: cannot comment the session of %s: %s", task, written.output)

    def _decide(
        self, readings: list[Reading], skipped: set[str], log: bool = True, lane: str | None = None
    ) -> tuple[list[dict[str, Any]], list[Decision]]:
        """The open tasks with the running, `skipped` and merged ones unworkable, and `decide`'s verdict on them over
        `readings`, for `lane` (the eligible lane by default)."""
        now = self._clock()
        cooling = {task for task in self._starts if self._cooling(task, now)}
        held = set(self._running) | skipped | cooling | self._held | self._resident()
        live = self._live()
        tasks = [self._candidate(agent, held, live) for agent in self._feed.open_tasks()]
        decisions = decide(
            tasks,
            lane or self._lane,
            readings,
            self._policy,
            self._ledger,
            log=log,
            refusals_logged=self._refusals_logged if lane is None else None,
        )
        if log:
            self._count(decisions)
        return tasks, decisions

    def _resident(self) -> set[str]:
        """The eligible-lane tasks a live session still holds: a park wake returns a Waiting task to Ready while the
        session that was parked runs on, and a second session would work the same branch beside it. Only `active` counts:
        a `stopped` session on a Ready task is one that ended its turn, which the start cooldown already covers."""
        now = self._clock()
        resident = set()
        for agent in self._feed.open_tasks():
            seen = self._feed.machine_task(HARNESS.name, agent["id"]) if agent["state"] == self._lane else None
            if seen is not None and seen["state"] == "active" and now - seen["active"] <= STALE_S:
                resident.add(agent["id"])
        return resident

    def _live(self) -> set[str]:
        """The In Progress tasks a session outside `_running` holds: one the harness or its transcript shows at work."""
        outside = self._outside()
        return {*outside, *self._transcribed(outside)}

    def _candidate(self, agent: dict[str, Any], held: set[str], live: set[str]) -> dict[str, Any]:
        """`agent` as `decide` sees it: unworkable when held or delivered, and a task a verify miss sent back to In
        Progress (the `regression` label) with no live session in the eligible lane, where it is picked as Ready work."""
        if agent["id"] in held or self._delivered(agent):
            return {**agent, "workable": False}
        sent_back = agent["state"] == self._feed.roles.working and REGRESSION in agent["labels"]
        return {**agent, "state": self._lane} if sent_back and agent["id"] not in live else agent

    def _delivered(self, agent: Mapping[str, Any]) -> bool:
        """Whether the eligible task's own pull request has merged: its work is done, so a session would only close it."""
        return agent["state"] == self._lane and agent["workable"] and self._merged(agent)

    def _count(self, decisions: list[Decision]) -> None:
        """Add this pass's verdicts to the store's tally, which the server's `/metrics` reads."""
        counts = Counter("admitted" if decision.admitted else "refused" for decision in decisions)
        if counts:
            tally = Counter(self._kept_state(TALLY_KEY) or {})
            tally.update(counts)
            self._keep_state(TALLY_KEY, dict(tally))
            gates = Counter(f"{gate}/{verdict}" for decision in decisions for gate, verdict in gate_verdicts(decision))
            gate_tally = Counter(self._kept_state(GATE_TALLY_KEY) or {})
            gate_tally.update(gates)
            self._keep_state(GATE_TALLY_KEY, dict(gate_tally))

    def next_pick(self) -> dict[str, Any] | None:
        """The task the next pass would start, or, when none fits, the top-ranked one and the dimension it waits on.

        Read for `GET /api/admin`, so it decides over the sampler's last reading without sampling and logs nothing;
        None before the first sample or with no workable task in the eligible lane. It does not depend on the switch; inside
        quiet hours the top task waits for them, whatever room the host has, and with no account that has room it waits for one.
        """
        if not self._sampler.readings()[0]:
            return None
        tasks, decisions = self._decide(self.readings(), set(), log=False)
        if not decisions:
            return None
        top = decisions[0]  # the admitted in enforced order come first, then the refused in the same order
        agent = next(a for a in tasks if a["id"] == top.task)
        now = self._clock()
        pause = self._selected_paused(now)
        full = self._full[1] > now
        roomless = not self._room()
        waits = not top.admitted or self._quiet(now) or pause is not None or full or roomless
        if not top.admitted:
            reason = top.blocked_by
        elif self._quiet(now):
            reason = "quiet hours"
        elif pause is not None:
            reason = f"{pause} {self._paused[pause]['reason']}"
        elif full:
            reason = START_LIMIT
        elif roomless:
            reason = "no account has room"
        else:
            reason = "goes next"
        return {
            "task": top.task,
            "title": agent["title"],
            "verdict": "waits" if waits else "starting",
            "reason": reason,
            "priority": top.priority,
        }

    def blocks(self) -> list[dict[str, Any]]:
        """Every gate holding admission back now, each with its use and limit: every dimension the top task overfits, and
        `start-limit` with its refusal count while the session-start service's limit is full. Empty before the first sample."""
        if not self._sampler.readings()[0]:
            return self._block_rows([], (), self._clock())
        readings = self.readings()
        _, decisions = self._decide(readings, set(), log=False)
        return self._block_rows(readings, decisions[0].overfit if decisions else (), self._clock())

    def gate_history(self, limit: int = GATE_HISTORY_MAX) -> list[dict[str, Any]]:
        """The last `limit` rows of gate readings and block reasons, oldest first, kept in the worker state."""
        raw = self._kept_state(GATE_HISTORY_KEY)
        rows = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
        return rows[-limit:]

    def _block_rows(self, readings: list[Reading], overfit: tuple[str, ...], now: float) -> list[dict[str, Any]]:
        by_name = {reading.name: reading for reading in readings}
        rows: list[dict[str, Any]] = [
            {"name": name, "use": by_name[name].use, "limit": by_name[name].limit}
            for name in overfit
            if name in by_name
        ]
        if self._full[1] > now:
            use, limit = self._full_counts
            rows.append({"name": START_LIMIT, "use": float(use), "limit": float(limit), "count": self._full[0]})
        return rows

    def _record(self, now: float, readings: list[Reading], decisions: list[Decision]) -> None:
        """Keep a row of this pass's readings and block reasons when the reasons changed or `GATE_HISTORY_EVERY` passed."""
        rows = self._block_rows(readings, decisions[0].overfit if decisions else (), now)
        history = self.gate_history()
        if history and now - history[-1]["at"] < GATE_HISTORY_EVERY:
            if [row["name"] for row in history[-1]["blockedBy"]] == [row["name"] for row in rows]:
                return
        dimensions = [{"name": r.name, "use": r.use, "limit": r.limit} for r in readings]
        history.append({"at": now, "dimensions": dimensions, "blockedBy": rows})
        self._keep_state(GATE_HISTORY_KEY, history[-GATE_HISTORY_MAX:])

    def _admit(self, now: float) -> list[str]:
        started: list[str] = []
        if self._full[1] > now:  # the session limit is full: every start would be refused
            readings = self.readings()
            self._record(now, readings, self._decide(readings, set(), log=False)[1])
            return started
        last: tuple[list[Reading], list[Decision]] | None = None
        skipped = set(start_requests.failed(self._log)) if self._log is not None else set()  # the task actor parks these
        while readings := self.readings():
            tasks, decisions = self._decide(readings, skipped)
            last = (readings, decisions)
            prompt: dict[str, Any] = {}
            if (picked := next((d for d in decisions if d.admitted), None)) is None and self._policy.verify_lane:
                # the eligible lane has nothing admissible: a task awaiting verification takes the room, on the verify profile
                tasks, decisions = self._decide(readings, skipped, lane=self._policy.verify_lane)
                picked = next((d for d in decisions if d.admitted), None)
                prompt = {"verb": "Verify", "profile": self._policy.verify_profile}
            if picked is None:
                break
            agent = next(a for a in tasks if a["id"] == picked.task)
            harness = self.selected_harness()
            try:
                session = self._start(picked.task, harness=harness, **prompt)
            except StartFailedError as exc:
                logger.warning("StarPulse scheduler: cannot start %s: %s", picked.task, exc)
                self._note_limit(str(exc), now, harness)
                self._note_halt(str(exc), now, harness)
                if sessions_full(str(exc)):
                    self._note_full(now, str(exc))
                    break
                if self._selected_paused(now):
                    break
                skipped.add(picked.task)
                if self._log is not None and not transient(str(exc)):
                    start_requests.fail(self._log, picked.task, str(exc))
                continue
            self._full = (0, 0.0)
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
            logger.info("StarPulse scheduler: started %s at %s", picked.task, session)
            self._note_claim(picked.task, session)
        if last is not None:
            self._record(now, *last)
            self._blocked = not any(d.admitted for d in last[1]) and bool(last[1] and last[1][0].overfit)
        return started

    def _hold(self, task: str) -> None:
        self._held.add(task)
        self._save_held()

    def _revive(self, now: float, agents: Mapping[str, Mapping[str, Any]]) -> None:
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
                self._running[task] = parked if parked is not None else self._stub(task, now, agents)
        if revived:
            self._save_held()
            self._remember()

    def _stub(self, task: str, now: float, agents: Mapping[str, Mapping[str, Any]]) -> _Run:
        agent = agents.get(task) or {"labels": (), "model": ""}
        return _Run(
            "",
            tier_of(agent),
            points(agent["labels"], self._policy.unsized_points),
            now,
            demand(agent, self._policy, self._ledger),
            self._use(),
            harness=self.selected_harness(),
        )

    def _release(self, now: float, agents: Mapping[str, Mapping[str, Any]]) -> None:
        """Drop a hold once the task leaves Ready and In Progress, or once it is Ready and its stopped run has cooled:
        a person or the sweep moved it, or the cooldown that guards a restart has passed."""
        kept = set()
        for task in self._held:
            agent = agents.get(task)
            if agent is None:
                continue
            if agent["state"] == self._feed.roles.working or (
                agent["state"] in self._lanes() and self._cooling(task, now)
            ):
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
        record(
            self._ledger.log,
            "usage_limit",
            self._paused.get(harness, {}).get("until"),
            resume,
            harness=harness,
            selected=harness == self.selected_harness(),
        )
        self._paused[harness] = {"until": resume, "reason": "usage limit"}
        self._save_pauses()

    def _note_halt(self, text: str, now: float, harness: str) -> None:
        """Halt admission for `harness` on a failure only a host change cures, raising it once for the whole halt."""
        if not permanent(text) or harness in self._paused:
            return
        self._paused[harness] = {"until": now + START_HALT, "reason": f"start halted: {text}"}
        self._save_pauses()
        logger.error("StarPulse scheduler: admission for %s halted for %d minutes: %s", harness, START_HALT // 60, text)

    def _note_full(self, now: float, text: str) -> None:
        refusals = self._full[0] + 1
        self._blocked = True
        self._full_counts = session_counts(text) or self._full_counts
        self._full = (
            refusals,
            now + min(START_BACKOFF * 2 ** min(refusals - 1, BACKOFF_EXPONENT_MAX), SESSIONS_FULL_BACKOFF_MAX),
        )

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
        raw = self._kept_state(HELD_KEY)
        if not isinstance(raw, list):
            return set()
        return {item for item in raw if isinstance(item, str)}

    def _load_pauses(self) -> dict[str, dict[str, Any]]:
        raw = self._kept_state(PAUSES_KEY)
        if not isinstance(raw, dict):
            return {}
        loaded: dict[str, dict[str, Any]] = {}
        for name, row in raw.items():
            if isinstance(name, str) and isinstance(row, dict) and isinstance(row.get("until"), (int, float)):
                loaded[name] = {"until": float(row["until"]), "reason": str(row.get("reason") or "usage limit")}
        return loaded

    def _save_held(self) -> None:
        self._keep_state(HELD_KEY, sorted(self._held))

    def _save_pauses(self) -> None:
        self._keep_state(PAUSES_KEY, self._paused)

    def _kept_state(self, key: str) -> Any:
        try:
            return self._ledger.log.state(key)[1]
        except Exception:  # an unreadable store holds nothing back
            logger.exception("StarPulse scheduler: cannot read %s", key)
            return None

    def _keep_state(self, key: str, value: Any) -> None:
        try:
            self._ledger.log.put_state(key, value)
        except Exception:  # a failed write must not stop the loop
            logger.exception("StarPulse scheduler: cannot write %s", key)
