"""The lane followers' metrics across the event log: the contexts worker runs them and keeps their exposition, the Page API relays it on `/metrics`."""

import logging
import threading
from collections.abc import Callable, Collection
from typing import Any

from starpulse.board.adapters.board_files import BoardFiles
from starpulse.event_log import lane_events
from starpulse.event_log.conformance_monitor import Conformance
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.kept_text import kept_text
from starpulse.event_log.wake import StopEvent

logger = logging.getLogger(__name__)

METRICS = "lanes.metrics"
PUBLISH_S = 10.0


def start(
    feed: Any,
    board: Any,
    log: EventLog,
    stop: StopEvent,
    work: Collection[str] = (),
    publish_s: float = PUBLISH_S,
    vectors: Callable[[], tuple[int, int]] | None = None,
) -> None:
    """Run the unattributed-lane count and the conformance monitor (`work`: the machines whose events are work) until
    `stop`, register the `board-files` pass over `feed` and `board` for the sweeper (`vectors` embeds the tasks that
    hold none), and keep their exposition in `log` every `publish_s` seconds."""
    unattributed = lane_events.Unattributed()
    unattributed.follow(log, stop)
    conformance = Conformance(
        feed.machines,
        entered=(feed.roles.done, lane_events.ARCHIVED),
        working=feed.roles.working,
        open_tasks=feed.open_tasks,
        review=feed.roles.review,
        work=work,
    )
    conformance.follow(log, stop)
    files = BoardFiles(feed, board, rescan=getattr(board, "rescan", None), vectors=vectors)
    feed.reconcilers["board-files"] = files.run

    def keep() -> None:
        # adr-exempt: pending
        while not stop.wait(publish_s):
            try:
                log.put_state(METRICS, unattributed.exposition() + conformance.exposition() + files.exposition())
            except Exception:
                logger.warning("lane-metrics: the metrics were not kept", exc_info=True)

    threading.Thread(target=keep, name="lane-metrics", daemon=True).start()


def metrics_of(log: EventLog) -> Callable[[], str]:
    """The followers' metrics text as last kept; empty before any was kept or when the log cannot be read."""
    return kept_text(log, METRICS)
