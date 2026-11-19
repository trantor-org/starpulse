"""The events that tell a task's holder it went idle: a harness session settling on the task's branch, or another
session moving the task it parked back to In Progress."""

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from sqlalchemy import Engine, select

from starpulse.event_log.events import STREAM as MACHINE_STREAM
from starpulse.event_log.lane_events import STREAM as LANE_STREAM
from starpulse.event_log.tables import machine_events
from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry, EventLog

HARNESS_MACHINE = "harness"
SETTLED = "SESSION_SETTLED"
STOPPED = "SESSION_STOPPED"  # a turn's end, which trails a settle and says nothing of whether the session is idle
WORKING = "in_progress"
PARKED = frozenset({"needs_attention", "waiting", "done"})  # lanes whose holder ended its turn before the move


def _task_of(entry: Entry, event: str) -> str | None:
    """The task whose branch's session `entry` reports as `event`, else None."""
    fields = entry.fields
    moved = fields.get("machine") == HARNESS_MACHINE and fields.get("event") == event
    return fields.get("task") if entry.stream == MACHINE_STREAM and moved else None


def _idle(engine: Engine, task: str, until: float) -> bool:
    """Whether the newest harness event of `task` up to `until`, a stop apart, is a settle: one indexed lookup."""
    c = machine_events.c
    newest = (
        select(c.event)
        .where(c.task == task, c.machine == HARNESS_MACHINE, c.event != STOPPED, c.occurred_at <= until)
        .order_by(c.occurred_at.desc(), c.id.desc())
        .limit(1)
    )
    with engine.connect() as db:
        return db.execute(newest).scalar() == SETTLED


def follow_holder_idle(
    settled: Callable[[str], None],
    log: EventLog,
    stop: StopEvent,
    ready: threading.Event,
    working: Callable[[], list[str]],
) -> threading.Thread:
    """Call `settled` with the task of each session that settles, and of each task moved from a parked lane to In
    Progress, after this call, within the event's own latency. The mover may not be the holder, which settled when it
    parked the task and settles no more, so the move is the only event that tells it. A task parked before this call
    and moved after a server restart is not seen, because the lane map starts empty.

    Once `ready` is set (the actor has indexed its tasks) it also calls `settled` once with each task of `working`
    whose newest harness event before this call, a `SESSION_STOPPED` aside, is a settle: its holder settled while the
    actor was down and was not started again since. The cost is one indexed lookup per working task, never a read of
    the stream. Nothing is called before `ready`, and the live tail's rows wait for it."""
    from starpulse.event_log.event_log import Tail  # the server imports no database stack until a store opens

    lanes: dict[str, str] = {}

    def handle(entry: Entry) -> None:
        if entry.stream == LANE_STREAM:
            task, lane = entry.fields.get("task", ""), entry.fields.get("lane", "")
            if lane == WORKING and lanes.get(task) in PARKED:
                settled(task)
            lanes[task] = lane
        elif task := _task_of(entry, SETTLED):
            settled(task)

    def run() -> None:
        stop.listen(ready.set)  # a stop wakes the wait below, which then sees it
        if not stop.is_set():
            ready.wait()
        if stop.is_set():
            return

        def follow() -> None:
            # a failed pass raises, and `run_on_wake` reads again before any settle is called
            idle = [task for task in working() if _idle(log.engine, task, started)]
            for task in idle:
                settled(task)
            tail.run(handle, stop)

        log.run_on_wake(stop, follow, "holder idle: cannot read the settles while the actor was down")

    started = time.time()  # the lookup stops here; the live tail reads what follows
    tail = Tail.live(log, MACHINE_STREAM, streams=[MACHINE_STREAM, LANE_STREAM])
    thread = threading.Thread(target=run, name="board-holder-idle", daemon=True)
    thread.start()
    return thread
