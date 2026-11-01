"""`starpulse worker pulls`: the Delivery context as its own process, beside `serve`.

It is the pull request store's projection from the machine events and its manual refresh, the task actor and the
release of dependents. It reads the config and the history database `serve` does and meets `serve` only in the event log
(`starpulse.pulls.adapters.inbound.delivery`): it keeps the pull request projection there, takes the refreshes a page asked and relays the
actor's metrics. `SIGTERM` stops it; `SIGHUP` re-reads the config and, when a Delivery setting changed, rebuilds the
loops in the same process.
"""

from __future__ import annotations

import argparse
import logging
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.pulls.adapters.inbound.delivery import (
    Projected,
    Publisher,
    announce_saves,
    follow_events,
    follow_refreshes,
    keep_metrics,
)
from starpulse.pulls.adapters.outbound.pull_events import JOBS_STREAM, MACHINE_STREAM, RecordProjection
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.pulls.bin.blocks import PullsConfig, pulls_delivery_blocks, pulls_fixed_blocks
from starpulse.pulls.model.pins import GitHub

logger = logging.getLogger(__name__)


class Delivery:
    """The Delivery loops of one config, taken down and built again in this process when a reload changes them."""

    def __init__(
        self,
        config: PullsConfig,
        board: Board,
        feed: BoardFeed,
        log: EventLog,
        pulls: PullStore,
        pins: GitHub,
        start_delivery: Callable[..., tuple[Any, Any]],
        *,
        resume: bool = False,
    ) -> None:
        self._config = config
        self._built = (board, feed, log, pulls, pins)
        self._start_delivery = start_delivery
        self._stop = threading.Event()
        #: Whether the replay resumes after the cursor the replays before kept (`follow_events`).
        self._resume = resume

    def start(self) -> None:
        """Start the loops of the running config, each ending when `stop` is called. Raises `ValueError` as
        `start_delivery` does."""
        board, feed, log, pulls, pins = self._built
        self._stop = stop = threading.Event()
        try:
            actor, sync = self._start_delivery(
                self._config,
                board,
                feed,
                log,
                pulls,
                pins,
                stop,
                after_project=Publisher(log, feed).publish,
            )
        except ValueError:
            stop.set()
            raise
        if sync:
            follow_refreshes(log, sync.request, stop)
            projection = RecordProjection(pulls, feed, sync.project)
            handlers = {MACHINE_STREAM: projection.handle, JOBS_STREAM: projection.handle_job}
            follow_events(log, feed, handlers, stop, resume=self._resume)
            self._resume = True  # a reload resumes after this replay's cursor
        if actor:
            keep_metrics(log, actor.exposition, stop)

    def stop(self) -> None:
        self._stop.set()

    def reload(self, path: Path, load: Callable[[Path | None], PullsConfig]) -> None:
        """Re-read `path`. An invalid config is logged and the running loops kept; a changed Delivery block takes them
        down and builds them again from the new config, and one the new config cannot build leaves the old config's
        loops running again."""
        try:
            new = load(path)
        except (OSError, ValueError) as exc:
            logger.error("reload: %s: %s; keeping the running config", path, exc)
            return
        if pulls_fixed_blocks(new) != pulls_fixed_blocks(self._config):
            logger.warning("reload: the database or board changed; restart the worker to apply it")
        if pulls_delivery_blocks(new) == pulls_delivery_blocks(self._config):
            logger.info("reload: no Delivery setting changed")
            return
        logger.info("reload: a Delivery setting changed; rebuilding the loops")
        running = self._config
        self.stop()
        self._config = new
        try:
            self.start()
        except ValueError as exc:
            logger.error("reload: %s; keeping the running config", exc)
            self._config = running
            self.start()


def start(
    config: PullsConfig,
    path: Path | None,
    base: Path,
    log: EventLog,
    stop: threading.Event,
    *,
    load: Callable[[Path | None], PullsConfig],
    worker_board: Callable[..., tuple[Board, BoardFeed]],
    history_store: Callable[[PullsConfig, Path, Mapping[str, dict]], Any],
    start_delivery: Callable[..., tuple[Any, Any]],
) -> Callable[[], None]:
    """Start the Delivery loops over `log`, each ending when `stop` is set, and return their reload. Raises
    `ValueError` as `worker_board` and `start_delivery` do."""
    board, feed = worker_board(config, base, log, stop)
    # the task actor records the lane of each write it makes under its own name; the placements of the Board are `serve`'s
    feed.record_lanes(history_store(config, base, feed.machines), log, live=False)
    Projected(log, feed).apply()  # the pull request answers the pins read: the Board's checkpoint no longer holds them
    pins = GitHub(lambda: feed.pull_answers().get("pins", {}))
    store = PullStore(log.engine)
    announce_saves(store, log)  # `serve` holds records in memory and takes each save from the database again
    # a store that holds records was built by the replays before; a new or wiped one rebuilds from the whole retention.
    # Read before any loop writes a record.
    delivery = Delivery(config, board, feed, log, store, pins, start_delivery, resume=bool(store.repos()))
    delivery.start()
    return lambda: delivery.reload(path, load)


def main(
    argv: list[str] | None,
    parser: argparse.ArgumentParser,
    *,
    discover: Callable[[Path | None], Path | None],
    load: Callable[[Path | None], PullsConfig],
    worker_board: Callable[..., tuple[Board, BoardFeed]],
    history_store: Callable[[PullsConfig, Path, Mapping[str, dict]], Any],
    start_delivery: Callable[..., tuple[Any, Any]],
    hold: Callable[[threading.Event, Callable[[], None]], None],
) -> None:
    """Run the Delivery worker; `runtime` passes the collaborators it builds, as no context imports it."""
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")
    base = args.config.parent if args.config else Path.cwd()
    log = EventLog(database_url(config.database_url, base))
    stop = threading.Event()
    try:
        reload_config = start(
            config,
            path,
            base,
            log,
            stop,
            load=load,
            worker_board=worker_board,
            history_store=history_store,
            start_delivery=start_delivery,
        )
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    hold(stop, reload_config)
