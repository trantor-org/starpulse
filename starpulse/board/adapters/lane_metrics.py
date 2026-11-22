"""The lane followers' metrics across the event log: the contexts worker runs them and keeps their exposition, the Page API relays it on `/metrics`."""

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
STALLS = "lanes.stalls"
#: Seconds between the writes a replay makes, so the remaining-entries gauge in the kept text falls while the monitor reads on.
PROGRESS_S = 10.0


def start(
    feed: Any,
    board: Any,
    log: EventLog,
    stop: StopEvent,
    work: Collection[str] = (),
    vectors: Callable[[], tuple[int, int]] | None = None,
    sessions: Mapping[str, dict] = {},
    types: Collection[str] = (),
) -> None:
    """Run the unattributed-lane count and the conformance monitor (`work`: the machines whose events are work) until
    `stop`, register the `board-files` pass over `feed` and `board` for the sweeper (`vectors` embeds the tasks that
    hold none, `sessions` the harness machine the monitor judges beside the board's), and keep their exposition in `log` once at start and after each entry or pass that changed it, the
    monitor's entries once it has read the log it found and every `PROGRESS_S` before, since a write per replayed
    entry outpaced no replay. The
    stalled gauge ages with no entry, so `log` keeps its deadlines and `metrics_of` counts them at scrape."""
    unattributed = lane_events.Unattributed()
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
    files = BoardFiles(feed, board, vectors=vectors)
    written: tuple[str, dict[str, Any]] | None = None
    guard = threading.Lock()

    def keep() -> None:
        nonlocal written
        with guard:
            try:
                found = (
                    unattributed.exposition() + conformance.exposition(stalled=False) + files.exposition(),
                    conformance.stall_state(),
                )
                if found != written:
                    log.put_state(METRICS, found[0])
                    log.put_state(STALLS, found[1])
                    written = found
            except Exception:
                logger.warning("lane-metrics: the metrics were not kept", exc_info=True)

    def sweep() -> tuple[int, int]:
        try:
            return files.run()
        finally:
            keep()

    next_write = time.monotonic() + PROGRESS_S

    def progress() -> None:
        nonlocal next_write
        if conformance.caught_up() or time.monotonic() >= next_write:
            next_write = time.monotonic() + PROGRESS_S
            keep()

    unattributed.follow(log, stop, keep)
    conformance.follow(log, stop, after=progress)
    feed.reconcilers["board-files"] = sweep
    keep()


def metrics_of(log: EventLog, clock: Callable[[], float] = time.time) -> Callable[[], str]:
    """The followers' metrics text as last kept, with the stalled gauge counted at `clock`; empty before any was kept
    or when the log cannot be read."""
    kept, stalls = kept_text(log, METRICS), kept_state(log, STALLS)
    return lambda: (text := kept()) and text + stalled_exposition(stalls(), clock())
