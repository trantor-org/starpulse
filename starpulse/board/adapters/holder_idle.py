"""The events that tell a task's holder it went idle or died: a harness session settling or ending on the task's
branch, or another session moving the task it parked back to In Progress."""

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from sqlalchemy import Engine, select

from starpulse.event_log.events import STREAM as MACHINE_STREAM
from starpulse.event_log.lane_events import STREAM as LANE_STREAM
from starpulse.event_log.readmodel import task_uuid
from starpulse.event_log.tables import events as log_events
from starpulse.event_log.tables import machine_events
from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry, EventLog

HARNESS_MACHINE = "harness"
SETTLED = "SESSION_SETTLED"
ENDED = "SESSION_ENDED"
DISPATCHED = "SESSION_DISPATCHED"
STOPPED = "SESSION_STOPPED"  # a turn's end, which trails a settle and says nothing of whether the session is idle
WORKING = "in_progress"
PARKED = frozenset({"needs_attention", "waiting", "done"})  # lanes whose holder ended its turn before the move
UNREACHABLE_EXIT = 3  # the `[board] idle` resume found no session subscribed to the task's resume topic
GRACE_EXIT = 4  # the `[board] idle` confirm found the holder busy only because it launched a `deliver` a moment ago


class HolderUnreachable(ValueError):
    """The idle hook's resume reached no session: a retry on the next settle wakes no one, and none may come."""


class HolderInGrace(ValueError):
    """The idle hook's confirm found the holder busy only inside the grace after it launched a `deliver`: the grace ends
    on a clock, so no event follows it."""


def _task_of(entry: Entry, event: str) -> str | None:
    """The task whose branch's session `entry` reports as `event`, else None."""
    fields = entry.fields
    moved = fields.get("machine") == HARNESS_MACHINE and fields.get("event") == event
    return fields.get("task") if entry.stream == MACHINE_STREAM and moved else None


def _session_of(entry: Entry, key: str = "session") -> str:
    """The session a dispatch or an end names under `key` in its data, else empty."""
    return str((entry.fields.get("data") or {}).get(key) or "")


def dispatcher(log: EventLog) -> Callable[[str, str, str], bool]:
    """What publishes the dispatch of a session to a task, naming the holder it replaces when the caller found one dead,
    and says whether the log appended it."""
    from starpulse.event_log import events  # the server imports no database stack until a store opens

    def dispatch(task: str, session: str, replaces: str) -> bool:
        data = {"session": session, **({"replaces": replaces} if replaces else {})}
        published = events.publish(HARNESS_MACHINE, DISPATCHED, actor="starpulse", task=task, data=data, log=log)
        return published is not None

    return dispatch


def started(engine: Engine, task: str) -> bool:
    """Whether a session was ever dispatched to `task`: the start event is where its started state is read."""
    c = machine_events.c
    found = select(c.id).where(c.task_uuid == task_uuid.of(task), c.machine == HARNESS_MACHINE, c.event == DISPATCHED).limit(1)
    with engine.connect() as db:
        return db.execute(found).first() is not None


def _newest(engine: Engine, task: str, until: float) -> tuple[str, dict[str, str]] | None:
    """The newest harness event of `task` up to `until`, a stop apart, and the data its log entry holds: one indexed lookup."""
    c = machine_events.c
    newest = (
        select(c.event, log_events.c.fields)
        .select_from(machine_events.outerjoin(log_events, log_events.c.event_id == c.event_id))
        .where(c.task_uuid == task_uuid.of(task), c.machine == HARNESS_MACHINE, c.event != STOPPED, c.occurred_at <= until)
        .order_by(c.occurred_at.desc(), c.id.desc())
        .limit(1)
    )
    with engine.connect() as db:
        row = db.execute(newest).first()
    return None if row is None else (row.event, (row.fields or {}).get("data") or {})


def follow_holder_idle(
    settled: Callable[[str], None],
    log: EventLog,
    stop: StopEvent,
    ready: threading.Event,
    working: Callable[[], list[str]],
    ended: Callable[[str], None] = lambda _task: None,
    entered: Callable[[str], None] | None = None,
    moved: Callable[[str, str], None] = lambda _task, _lane: None,
    dispatched: Callable[[str, str], None] = lambda _task, _session: None,
    lease_ended: Callable[[str, str], None] = lambda _task, _session: None,
    unstarted: Callable[[], list[str]] = list,
    closed: Callable[[], list[str]] = list,
) -> threading.Thread:
    """Call `settled` with the task of each session that settles, and `entered` (`settled` when none) with each task
    moved from a parked lane to In Progress, after this call, within the event's own latency; call `ended` with the task
    of each session whose process ends, `lease_ended` first with that task and the session, `dispatched` with the task and
    session of each dispatch, and `moved` with each task and the lane it entered. The mover may not be the holder, which settled when it
    parked the task and settles no more, so the move is the only event that tells it. A task parked before this call
    and moved after a server restart is not seen, because the lane map starts empty.

    Once `ready` is set (the actor has indexed its tasks) it also calls `settled` once with each task of `working`
    whose newest harness event before this call, a `SESSION_STOPPED` aside, is a settle (`settled`) or an end (`lease_ended` with the session its entry names, then `ended`):
    its holder settled or died while the actor was down and was not started again since. The cost is one indexed lookup per working task, never a read of
    the stream. A task of `closed` (an open one in a lane that ends its idle session) gets the same `settled` call for any newest
    event but an end, which ends its session once idle: the move that closed the lane may have come while the actor was down, or its end
    been lost at a stop. It calls `dispatched` (`lease_ended` first for a dead holder it replaces) with each task of `working` or
    `unstarted` whose newest such event is a dispatch: the actor was down for it and pinned no session since. Nothing is called before `ready`, and the live tail's rows wait for it."""
    from starpulse.event_log.event_log import Tail  # the server imports no database stack until a store opens
    from starpulse.event_log.follower_lag import HOLDER_IDLE, Behind

    lanes: dict[str, str] = {}
    behind = Behind(log, HOLDER_IDLE)

    def handle(entry: Entry) -> None:
        behind.handled(entry.at)
        if entry.stream == LANE_STREAM:
            task, lane = entry.fields.get("task", ""), entry.fields.get("lane", "")
            if lane == WORKING and lanes.get(task) in PARKED:
                (entered or settled)(task)
            lanes[task] = lane
            moved(task, lane)
        elif task := _task_of(entry, SETTLED):
            settled(task)
        elif task := _task_of(entry, DISPATCHED):
            if replaces := _session_of(entry, "replaces"):
                lease_ended(task, replaces)
            dispatched(task, _session_of(entry))
        elif task := _task_of(entry, ENDED):
            lease_ended(task, _session_of(entry))
            ended(task)

    def run() -> None:
        behind.since(started)  # trailing from the call until the lookup below is done
        stop.listen(ready.set)  # a stop wakes the wait below, which then sees it
        if not stop.is_set():
            ready.wait()
        if stop.is_set():
            return

        def follow() -> None:
            # a failed pass raises, and `run_on_wake` reads again before any settle is called
            tasks, shut = working(), closed()
            newest = {task: _newest(log.engine, task, started) or ("", {}) for task in [*tasks, *shut, *unstarted()]}
            for task in [task for task in tasks if newest[task][0] == SETTLED]:
                settled(task)
            for task in [task for task in shut if newest[task][0] not in ("", ENDED)]:
                settled(task)  # the reaper ends only an idle session, so a turn running now is left alone
            for task in [task for task in tasks if newest[task][0] == ENDED]:
                lease_ended(task, str(newest[task][1].get("session") or ""))
                ended(task)
            for task in [task for task, (event, _) in newest.items() if event == DISPATCHED]:
                data = newest[task][1]
                if replaces := str(data.get("replaces") or ""):
                    lease_ended(task, replaces)
                dispatched(task, str(data.get("session") or ""))
            behind.caught_up()
            tail.run(handle, stop)

        log.run_on_wake(stop, follow, "holder idle: cannot read the settles while the actor was down")

    started = time.time()  # the lookup stops here; the live tail reads what follows
    tail = Tail.live(log, MACHINE_STREAM, streams=[MACHINE_STREAM, LANE_STREAM])
    thread = threading.Thread(target=run, name="board-holder-idle", daemon=True)
    thread.start()
    return thread
