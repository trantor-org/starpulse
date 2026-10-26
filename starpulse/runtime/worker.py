"""`starpulse worker <context>`: one bounded context as its own process, beside `serve`.

`api` is the Page API, run by `starpulse.views.bin.api_worker` on the socket `serve` hands it; `pulls` is the Delivery context (the pull request store's projection from the machine events and its manual refresh, the task actor and the release of
dependents); `scheduler` is the Scheduler context, run by `starpulse.scheduler.bin.scheduler_worker`; `runs` is the
Runs context, run by `starpulse.runs.bin.runs_worker`; `dagu`, `github-actions` and `systemd` are the run Adapters, opt-in workers `serve` never starts, run by
`starpulse.runs.bin.adapter_worker`; `flow-metrics` is the Flow Metrics context, run by
`starpulse.flow_metrics.bin.flow_metrics_worker`; `search` is the Search context's embedding catch-up, run by
`starpulse.board.bin.search_worker`; `board` is the Board context's writer (the Start Criteria dating), run by `starpulse.board.bin.board_worker`.

The `pulls` worker reads the config and the history database `serve` does and meets `serve` only in the event log
(`starpulse.pulls.delivery`): it keeps the pull request projection there, takes the refreshes a page asked and
relays the actor's metrics. `SIGTERM` stops it; `SIGHUP` re-reads the config and, when a Delivery setting
changed, rebuilds the loops in the same process.
"""

from __future__ import annotations

import argparse
import logging
import threading
from pathlib import Path

from starpulse.runtime.blocks import pulls_delivery_blocks, pulls_fixed_blocks
from starpulse.board.model.seam import Board
from starpulse._internal.config.config import Config, discover, load
from starpulse._internal.config.pins import GitHub
from starpulse.board.board_feed import BoardFeed
from starpulse.pulls.delivery import (
    Projected,
    Publisher,
    announce_saves,
    follow_events,
    follow_refreshes,
    keep_metrics,
)
from starpulse.pulls.pull_events import JOBS_STREAM, MACHINE_STREAM, RecordProjection
from starpulse.pulls.pulls import PullStore
from starpulse.runtime.assembly import history_store, worker_board
from starpulse.runtime.hold import hold
from starpulse.runtime.server import listen_options, start_delivery
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url

logger = logging.getLogger(__name__)

#: The run Adapters that are opt-in workers (`starpulse.runs.bin.adapter_worker`): `serve` supervises none.
OPT_IN = ("dagu", "github-actions", "systemd")
CONTEXTS = ("api", "pulls", "scheduler", "runs", "flow-metrics", "search", "board", *OPT_IN)


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
                after_project=Publisher(log, feed).publish,
            )
        except ValueError:
            stop.set()
            raise
        if sync:
            follow_refreshes(log, sync.request, stop)
            projection = RecordProjection(pulls, feed, sync.project)
            follow_events(log, feed, {MACHINE_STREAM: projection.handle, JOBS_STREAM: projection.handle_job}, stop)
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


def worker_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="starpulse worker", description="Run one bounded context of StarPulse as its own process."
    )
    parser.add_argument(
        "context",
        choices=CONTEXTS,
        help="the bounded context to run",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="the config `serve` runs from; default: starpulse.toml in the working directory, else the defaults",
    )
    listen_options(parser)  # read by `api`: where the page listens when `serve` hands it no socket
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = worker_parser()
    args = parser.parse_args(argv)
    if args.context == "api":  # imported here: the other workers' closures hold no page
        from starpulse.views.bin import api_worker

        return api_worker.main(argv, parser)
    if args.context == "scheduler":  # imported here: the Delivery worker's closure holds no scheduler module
        from starpulse.scheduler.bin import scheduler_worker as worker

        return worker.main(argv, parser)
    if args.context == "runs":  # imported here: the Delivery worker's closure holds no run adapter module
        from starpulse.runs.bin import runs_worker

        return runs_worker.main(argv, parser)
    if args.context in OPT_IN:  # an opt-in worker: `serve` supervises none
        from starpulse.runs.bin import adapter_worker

        return adapter_worker.main(argv, parser, args.context)
    if args.context == "flow-metrics":
        from starpulse.flow_metrics.bin import flow_metrics_worker

        return flow_metrics_worker.main(argv, parser)
    if args.context == "search":
        from starpulse.board.bin import search_worker

        return search_worker.main(argv, parser)
    if args.context == "board":
        from starpulse.board.bin import board_worker

        return board_worker.main(argv, parser)
    path = discover(args.config)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")
    base = args.config.parent if args.config else Path.cwd()
    log = EventLog(database_url(config.database_url, base))
    stop = threading.Event()
    try:
        board, feed = worker_board(config, base, log, "starpulse-pulls", stop)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    # the task actor records the lane of each write it makes under its own name; the placements of the Board are `serve`'s
    feed.record_lanes(history_store(config, base, feed.machines), log, live=False)
    Projected(log, feed).apply()  # the pull request answers the pins read: the Board's checkpoint no longer holds them
    pins = GitHub(lambda: feed.pull_answers().get("pins", {}))
    store = PullStore(log.engine)
    announce_saves(store, log)  # `serve` holds records in memory and takes each save from the database again
    delivery = Delivery(config, board, feed, log, store, pins)
    try:
        delivery.start()
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    hold(stop, lambda: delivery.reload(path))
