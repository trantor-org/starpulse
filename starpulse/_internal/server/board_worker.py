"""`starpulse worker board`: the Board context's writer (the thread that dates when each Waiting task's Start Criteria
were met) as its own process, beside `serve`.

`board-release` is not here: the release of dependents runs in the Delivery worker (`starpulse worker pulls`).

It reads the config and the database `serve` does and meets `serve` only in the history there: this worker writes when
each task's criteria were met (`HistoryStore.save_criteria_met`), and `serve` rereads it on a timer
(`BoardFeed.follow_criteria`). The writer is resumable by construction: the dates are read back from the history at
start, so a task whose criteria stay met keeps the moment it was first seen so, and it waits for the Board to be read
before it evaluates, so a replay in progress forgets no date. `SIGTERM` stops it; `SIGHUP` re-reads the config and, as
the board and the writer are built once, only says whether a restart is needed.
"""

from __future__ import annotations

import argparse
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from starpulse._internal.board import replica
from starpulse._internal.config.config import Config, discover, load
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.server import read_model_follow
from starpulse._internal.server.assembly import assemble, history_store
from starpulse._internal.server.hold import hold
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.event_log.readmodel.declared import declared_fields
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore
from starpulse.flow_metrics.history import HistoryStore

logger = logging.getLogger(__name__)


def built_blocks(config: Config) -> tuple:
    """What of `config` the worker's board, history and lane log were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board)


def reload(path: Path, config: Config) -> None:
    """Re-read `path`; an invalid config is logged, and a change to what the worker was built from asks for a restart."""
    try:
        new = load(path)
    except (OSError, ValueError) as exc:
        logger.error("reload: %s: %s; keeping the running config", path, exc)
        return
    if built_blocks(new) != built_blocks(config):
        logger.warning("reload: a database or board setting changed; restart the worker to apply it")
    else:
        logger.info("reload: no Board setting changed")


def start_writers(
    feed: BoardFeed,
    store: HistoryStore,
    evaluate: Callable[[str, str], list[dict]] | None,
    stop: threading.Event,
    live: bool = True,
) -> threading.Thread:
    """Start the criteria thread, which runs until `stop` is set; it waits for `feed` to have read the Board. A `live`
    feed also records each lane a task enters as it places it; the Board child places none live, as `serve` records the
    ones its replica puts and the ones its writes make."""
    feed.date_lanes(store.lane_path)
    feed.record_lanes(store, live=live)
    feed.track_criteria(evaluate, store)

    def keep() -> None:
        feed.ready.wait()
        feed.keep_criteria(stop)

    criteria = threading.Thread(target=keep, name="board-criteria", daemon=True)
    criteria.start()
    return criteria


def main(argv: list[str] | None, parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")
    base = args.config.parent if args.config else Path.cwd()
    log = EventLog(database_url(config.database_url, base))
    model = ReadModel(log.engine, declared_fields(config.board)) if config.read_model else None
    try:
        board, feed = assemble(config, base, None, [], model)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    store = history_store(config, base, feed.machines)
    stop = threading.Event()
    if model is None:
        start_writers(feed, store, board.evaluate, stop, live=False)
        replica.publish(board, feed, "starpulse-board", log, config)
    else:
        # the read model replaces the task files as the board's reader: nothing publishes a replica of them
        feed.ready.set()
        start_writers(feed, store, board.evaluate, stop, live=False)
        read_model_follow.follow(Projector(log.engine, EventStore(log.engine)), feed, stop)
    hold(stop, lambda: reload(path, config))
