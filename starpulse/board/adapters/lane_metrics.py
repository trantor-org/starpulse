"""The lane followers' metrics across the event log: the contexts worker runs the unattributed count and the board-files
pass, the conformance worker the monitor; each keeps its exposition, the Page API relays both on `/metrics`."""

import logging
import threading
import time
from collections.abc import Callable, Collection, Mapping
from typing import Any

from starpulse.board.adapters.board_files import BoardFiles
from starpulse.event_log import lane_events
from starpulse.event_log.conformance_monitor import Conformance, stalled_exposition
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.kept_text import kept_state, kept_text
from starpulse.event_log.wake import StopEvent

logger = logging.getLogger(__name__)

METRICS = "lanes.metrics"
CONFORMANCE = "lanes.conformance"
STALLS = "lanes.stalls"
#: Seconds between the writes a replay makes, so the remaining-entries gauge in the kept text falls while the monitor reads on.
PROGRESS_S = 10.0


def start(feed: Any, board: Any, log: EventLog, stop: StopEvent, vectors: Callable[[], tuple[int, int]] | None = None) -> None:
    """Run the unattributed-lane count until `stop`, register the `board-files` pass over `feed` and `board` for the
    sweeper (`vectors` embeds the tasks that hold none), and keep their exposition in `log` once at start and after each
    entry or pass that changed it."""
    unattributed = lane_events.Unattributed()
    files = BoardFiles(feed, board, vectors=vectors)
    written: str | None = None
    guard = threading.Lock()

    def keep() -> None:
        nonlocal written
        with guard:
            try:
                found = unattributed.exposition() + files.exposition()
                if found != written:
                    log.put_state(METRICS, found)
                    written = found
            except Exception:
                logger.warning("lane-metrics: the metrics were not kept", exc_info=True)

    def sweep() -> tuple[int, int]:
        try:
            return files.run()
        finally:
            keep()

    unattributed.follow(log, stop, keep)
    feed.reconcilers["board-files"] = sweep
    keep()


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
    replay. The stalled gauge ages with no entry, so `log` keeps its deadlines and `metrics_of` counts them at scrape."""
    conformance = Conformance(
        feed.machines,
        entered=(feed.roles.done, lane_events.ARCHIVED),
        working=feed.roles.working,
        open_tasks=feed.open_tasks,
        review=feed.roles.review,
        work=work,
        sessions=sessions,
        done=feed.roles.done,
        types=types,
        busy=lambda task: "busy" in ((board.read(task) or {}).get("actorMemory") or {}),
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
