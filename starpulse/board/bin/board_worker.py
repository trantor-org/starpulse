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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from starpulse._internal.config.config import Config, discover, load
from starpulse.board.adapters import replica
from starpulse.board.bin.blocks import board_built_blocks
from starpulse.board.board_feed import BoardFeed, CriteriaStore, ExpiriesStore, LaneRecorder
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.event_log.readmodel.declared import declared_fields
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore

logger = logging.getLogger(__name__)


class WriterStore(LaneRecorder, CriteriaStore, ExpiriesStore, Protocol):
    """What the criteria thread keeps its dating in (`HistoryStore`)."""

    def lane_path(self, task: str) -> list[dict]: ...


def reload(path: Path, config: Config) -> None:
    """Re-read `path`; an invalid config is logged, and a change to what the worker was built from asks for a restart."""
    try:
        new = load(path)
    except (OSError, ValueError) as exc:
        logger.error("reload: %s: %s; keeping the running config", path, exc)
        return
    if board_built_blocks(new) != board_built_blocks(config):
        logger.warning("reload: a database or board setting changed; restart the worker to apply it")
    else:
        logger.info("reload: no Board setting changed")


def start_writers(
    feed: BoardFeed,
    store: WriterStore,
    evaluate: Callable[[str, str], list[dict]] | None,
    stop: threading.Event,
    live: bool = True,
    log: EventLog | None = None,
) -> threading.Thread:
    """Start the criteria thread, which runs until `stop` is set; it waits for `feed` to have read the Board. A `live`
    feed also records each lane a task enters as it places it; the Board child places none live, as `serve` records the
    ones its replica puts and the ones its writes make. `log` carries each lane change's actor to the `board:lanes`
    entry."""
    feed.date_lanes(store.lane_path)
    feed.record_lanes(store, log, live=live)
    feed.track_criteria(evaluate, store)

    def keep() -> None:
        feed.ready.wait()
        feed.keep_criteria(stop)

    criteria = threading.Thread(target=keep, name="board-criteria", daemon=True)
    criteria.start()
    return criteria


def main(
    argv: list[str] | None,
    parser: argparse.ArgumentParser,
    *,
    assemble: Callable[..., tuple[Board, BoardFeed]],
    history_store: Callable[[Config, Path, Mapping[str, dict]], WriterStore],
    follow: Callable[..., object],
    hold: Callable[[threading.Event, Callable[[], None]], None],
) -> None:
    """Run the Board writer; `runtime` passes the collaborators it builds (`assemble`, `history_store`, the read model's
    `follow` and `hold`), as no context imports it."""
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
        start_writers(feed, store, board.evaluate, stop, live=False, log=log)
        replica.publish(board, feed, "starpulse-board", log, config)
    else:
        # the read model replaces the task files as the board's reader: nothing publishes a replica of them
        feed.ready.set()
        start_writers(feed, store, board.evaluate, stop, live=False, log=log)
        if board.attach is not None:
            board.attach(log)  # the sweep's releases append the History events the read model folds
        if board.sweep is not None:
            board.sweep(feed, log, store.save_claim_expiries)
        follow(Projector(log.engine, EventStore(log.engine)), feed, stop)
    hold(stop, lambda: reload(path, config))
