"""The lane followers' metrics across the event log: the contexts worker runs the unattributed count, the conformance worker the monitor; each keeps its exposition, the Page API relays both on `/metrics`."""

import logging
import threading
import time
from collections.abc import Callable, Collection, Mapping
from typing import Any

from starpulse.board.adapters.board_files import embedding
from starpulse.event_log import lane_events, start_requests
from starpulse.event_log.conformance_monitor import Conformance, stalled_exposition
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.kept_text import kept_state, kept_text
from starpulse.event_log.wake import StopEvent
from starpulse.machine_engine.model.transitions import ARCHIVED

logger = logging.getLogger(__name__)

METRICS = "lanes.metrics"
CONFORMANCE = "lanes.conformance"
STALLS = "lanes.stalls"
#: Seconds between the writes a replay makes, so the remaining-entries gauge in the kept text falls while the monitor reads on.
PROGRESS_S = 10.0


def start(feed: Any, log: EventLog, stop: StopEvent, vectors: Callable[[], tuple[int, int]] | None = None) -> None:
    """Run the unattributed-lane count until `stop`, register the `board-files` pass for the sweeper (`vectors` embeds
    the tasks that hold none), and keep the count's exposition in `log` once at start and after each entry that changed it."""
    unattributed = lane_events.Unattributed()
    written: str | None = None
    guard = threading.Lock()

    def keep() -> None:
        nonlocal written
        with guard:
            try:
                found = unattributed.exposition()
                if found != written:
                    log.put_state(METRICS, found)
                    written = found
            except Exception:
                logger.warning("lane-metrics: the metrics were not kept", exc_info=True)

    unattributed.follow(log, stop, keep)
    feed.reconcilers["board-files"] = embedding(vectors)
    keep()


def held_busy(board: Any, log: EventLog) -> Callable[[str], bool]:
    """Whether a task is held busy: a running shell holds its settled session, the task actor awaits an event (a CI
    result, a merge) that wakes it, or its resume or nudge waits for the scheduler's admission gate, so a quiet session
    there is no idle one."""
    return lambda task: bool(
        {"busy", "awaited"} & ((board.read(task) or {}).get("actorMemory") or {}).keys()
    ) or task in start_requests.wanted(log)


def monitor(
    feed: Any,
    board: Any,
    log: EventLog,
    stop: StopEvent,
    work: Collection[str] = (),
    sessions: Mapping[str, dict] = {},
    types: Collection[str] = (),
) -> None:
    """Run the conformance monitor (`work`: the machines whose events are work; `sessions` the harness machine it judges
    beside the board's) until `stop`, and keep its exposition in `log` after each entry that changed it: the entries
    once it has read the log it found and every `PROGRESS_S` before, since a write per replayed entry outpaced no
    replay. The stalled gauge ages with no entry, so `log` keeps its deadlines and `metrics_of` counts them at scrape; a
    replay keeps the last deadlines, so the gauge stays sampled until it has read up."""
    conformance = Conformance(
        feed.machines,
        entered=(feed.roles.done, ARCHIVED, feed.roles.working),
        working=feed.roles.working,
        open_tasks=feed.open_tasks,
        review=feed.roles.review,
        work=work,
        sessions=sessions,
        done=feed.roles.done,
        types=types,
        busy=held_busy(board, log),
    )
    written: tuple[str, dict[str, Any]] | None = None
    guard = threading.Lock()  # a thread reads each stream
    next_write = time.monotonic() + PROGRESS_S

    def keep() -> None:
        nonlocal written
        with guard:
            try:
                found = (conformance.exposition(stalled=False), conformance.stall_state())
                if found != written:
                    log.put_state(CONFORMANCE, found[0])
                    if found[1]:  # empty while the streams are read up: keep the last deadlines, so a lag is no gap
                        log.put_state(STALLS, found[1])
                    written = found
            except Exception:
                logger.warning("conformance: the metrics were not kept", exc_info=True)

    def progress() -> None:
        nonlocal next_write
        if conformance.caught_up() or time.monotonic() >= next_write:
            next_write = time.monotonic() + PROGRESS_S
            keep()

    conformance.follow(log, stop, after=progress)
    keep()


def metrics_of(log: EventLog, clock: Callable[[], float] = time.time) -> Callable[[], str]:
    """The followers' metrics text as last kept by the two workers, with the stalled gauge counted at `clock`; empty
    before any was kept or when the log cannot be read."""
    counts, judged, stalls = kept_text(log, METRICS), kept_text(log, CONFORMANCE), kept_state(log, STALLS)
    return lambda: counts() + judged() + stalled_exposition(stalls(), clock())
