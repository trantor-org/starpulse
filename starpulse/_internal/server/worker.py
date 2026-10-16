"""`starpulse worker <context>`: one bounded context as its own process, beside `serve`.

`pulls` is the Delivery context (the pull request store's sync and projection, the task actor and the release of
dependents); `autopilot` is the Autopilot context, run by `starpulse._internal.autopilot.worker`.

The `pulls` worker reads the config and the history database `serve` does and meets `serve` only in the event log
(`starpulse._internal.pulls.delivery`): it keeps the pull request projection there, takes the refreshes a page asked and
relays the actor's notes and metrics. `SIGTERM` stops it; `SIGHUP` re-reads the config and, when a Delivery setting
changed, rebuilds the loops in the same process.
"""

from __future__ import annotations

import argparse
import logging
import threading
from pathlib import Path

from starpulse._internal.board.seam import Board
from starpulse._internal.config.config import Config, discover, load
from starpulse._internal.config.pins import GitHub
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import database_url
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.pulls.delivery import (
    NotingFeed,
    Publisher,
    follow_refreshes,
    keep_metrics,
)
from starpulse._internal.pulls.pulls import PullStore
from starpulse._internal.server.hold import hold
from starpulse._internal.server.server import assemble, start_delivery

logger = logging.getLogger(__name__)

CONTEXTS = ("pulls", "autopilot")


def delivery_blocks(config: Config) -> tuple:
    """What of `config` the Delivery loops are built from; a change to anything else needs no rebuild."""
    return (config.task_actor, config.release, config.repos, config.pull_requests, config.ci)


def fixed_blocks(config: Config) -> tuple:
    """What of `config` the worker's board and history database were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board)


class Delivery:
    """The Delivery loops of one config, taken down and built again in this process when a reload changes them."""

    def __init__(
        self, config: Config, board: Board, feed: BoardFeed, log: EventLog, pulls: PullStore, pins: GitHub
    ) -> None:
        self._config = config
        self._built = (board, feed, log, pulls, pins)
        self._stop = threading.Event()

    def start(self) -> None:
        """Start the loops of the running config, each ending when `stop` is called. Raises `ValueError` as
        `start_delivery` does."""
        board, feed, log, pulls, pins = self._built
        self._stop = stop = threading.Event()
        try:
            actor, sync = start_delivery(
                self._config,
                board,
                feed,
                log,
                pulls,
                pins,
                stop,
                actor_feed=NotingFeed(feed, log),
                after_project=Publisher(log, feed).publish,
            )
        except ValueError:
            stop.set()
            raise
        if sync:
            follow_refreshes(log, sync.request, stop)
        if actor:
            keep_metrics(log, actor.exposition, stop)

    def stop(self) -> None:
        self._stop.set()

    def reload(self, path: Path) -> None:
        """Re-read `path`. An invalid config is logged and the running loops kept; a changed Delivery block takes them
        down and builds them again from the new config, and one the new config cannot build leaves the old config's
        loops running again."""
        try:
            new = load(path)
        except (OSError, ValueError) as exc:
            logger.error("reload: %s: %s; keeping the running config", path, exc)
            return
        if fixed_blocks(new) != fixed_blocks(self._config):
            logger.warning("reload: the database or board changed; restart the worker to apply it")
        if delivery_blocks(new) == delivery_blocks(self._config):
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


def worker_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="starpulse worker", description="Run one bounded context of StarPulse as its own process."
    )
    parser.add_argument("context", choices=CONTEXTS, help="the bounded context to run")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="the config `serve` runs from; default: starpulse.toml in the working directory, else the defaults",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = worker_parser()
    args = parser.parse_args(argv)
    if args.context == "autopilot":  # imported here: the Delivery worker's closure holds no autopilot module
        from starpulse._internal.autopilot import worker

        return worker.main(argv, parser)
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
    board.start(feed, "starpulse-pulls", log)
    stop = threading.Event()
    pins = GitHub(lambda: feed.pull_answers().get("pins", {}))
    delivery = Delivery(config, board, feed, log, PullStore(log.engine), pins)
    try:
        delivery.start()
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    hold(stop, lambda: delivery.reload(path))
