"""`starpulse worker board`: the Board context's writers (the thread that dates when each Waiting task's Start Criteria
were met, and the reconcile that records the lanes the history missed) as their own process, beside `serve`.

`board-release` is not here: the release of dependents runs in the Delivery worker (`starpulse worker pulls`).

It reads the config and the database `serve` does and meets `serve` only in the history there: this worker writes when
each task's criteria were met (`HistoryStore.save_criteria_met`) and the lane rows the history lacks, and `serve` rereads
the first on a timer (`BoardFeed.follow_criteria`). Both writers are resumable by construction. The dates are read back
from the history at start, so a task whose criteria stay met keeps the moment it was first seen so, and the writers
wait for the Board to be read before they evaluate, so a replay in progress forgets no date. The reconcile records a
lane under an id naming the task, the lane and when it entered it, so a new process records exactly what the last one
left and neither drops nor repeats a lane row. `SIGTERM` stops it; `SIGHUP` re-reads the config and, as the board and
the writers are built once, only says whether a restart is needed.
"""

from __future__ import annotations

import argparse
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from starpulse._internal.board import replica
from starpulse._internal.config.config import Config, discover, load
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import HistoryStore, database_url
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.server.hold import hold
from starpulse._internal.server.server import assemble, history_store
from starpulse._internal.server.writes import reconcile_lanes

logger = logging.getLogger(__name__)


def built_blocks(config: Config) -> tuple:
    """What of `config` the worker's board, history and lane log were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board, config.forward, config.triggers)


def reload(path: Path, config: Config) -> None:
    """Re-read `path`; an invalid config is logged, and a change to what the worker was built from asks for a restart."""
    try:
        new = load(path)
    except (OSError, ValueError) as exc:
        logger.error("reload: %s: %s; keeping the running config", path, exc)
        return
    if built_blocks(new) != built_blocks(config):
        logger.warning("reload: a database, board, forward or trigger setting changed; restart the worker to apply it")
    else:
        logger.info("reload: no Board setting changed")


def start_writers(
    feed: BoardFeed,
    store: HistoryStore,
    evaluate: Callable[[str, str], list[dict]] | None,
    stop: threading.Event,
    lane_log: EventLog | None = None,
    live: bool = True,
) -> tuple[threading.Thread, threading.Thread]:
    """Start the criteria thread, which runs until `stop` is set, and the lane reconcile, which ends after its one pass.
    Both wait for `feed` to have read the Board. A reconciled lane also reaches `lane_log`, for the hub it is forwarded
    to and the triggers that start a run on it. A `live` feed also records each lane a task enters as it places it; the
    Board child places none live, as `serve` records the ones its replica puts with whoever moved them."""
    feed.date_lanes(store.lane_path)
    feed.record_lanes(store, lane_log, live=live)
    feed.track_criteria(evaluate, store)

    def keep() -> None:
        feed.ready.wait()
        feed.keep_criteria(stop)

    criteria = threading.Thread(target=keep, name="board-criteria", daemon=True)
    reconcile = threading.Thread(target=reconcile_lanes, args=(feed, store), name="lane-reconcile", daemon=True)
    criteria.start()
    reconcile.start()
    return criteria, reconcile


def main(argv: list[str] | None, parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")
    base = args.config.parent if args.config else Path.cwd()
    try:
        board, feed = assemble(config, base, None, [])
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    log = EventLog(database_url(config.database_url, base))
    store = history_store(config, base, feed.machines)
    stop = threading.Event()
    lane_log = log if config.forward is not None or config.triggers else None
    start_writers(feed, store, board.evaluate, stop, lane_log, live=False)
    replica.publish(board, feed, "starpulse-board", log, config)
    hold(stop, lambda: reload(path, config))
