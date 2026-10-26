"""`starpulse worker scheduler`: the Scheduler context (the capacity sampler and the dispatch loop) as its own process,
beside `serve`.

It reads the config and the history database `serve` does and meets `serve` only in the event log
(`starpulse.scheduler.adapters.remote`): it publishes the status the page strip draws and wakes on the settings `serve`
writes. What a restart must keep (a task's one start, a harness's pause, the switch) is in that log, so a new process
resumes where the last stopped. `SIGTERM` stops it; `SIGHUP` re-reads the config and rebuilds the runtime in the same
process when a Scheduler setting changed.
"""

from __future__ import annotations

import argparse
import logging
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from starpulse._internal.config.config import Config, discover, load
from starpulse.board.board_feed import BoardFeed, follow
from starpulse.board.machine_tasks import MachineTasks
from starpulse.board.model.seam import Board
from starpulse.event_log import events as machine_events
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.flow_metrics.history import History
from starpulse.scheduler.adapters.remote import follow_wakes, publisher
from starpulse.scheduler.adapters.runtime import Runtime
from starpulse.scheduler.bin.blocks import scheduler_fixed_blocks, scheduler_live_blocks
from starpulse.scheduler.bin.scheduler_service import start_scheduler

logger = logging.getLogger(__name__)


class Scheduler:
    """The runtime of one config, taken down and built again in this process when a reload changes it."""

    def __init__(
        self,
        config: Config,
        base: Path,
        board: Board,
        feed: BoardFeed,
        log: EventLog,
        history: History,
        probe: Callable[[], Mapping[str, float]] | None = None,
        *,
        trajectories_response: Callable[..., tuple[bytes, int]],
        cached: Callable[[Callable[[], dict[str, Any]], float], Callable[[], dict[str, Any]]],
        starter: Callable[..., Any],
    ) -> None:
        self._config = config
        self._trajectories_response = trajectories_response
        self._cached = cached
        self._starter = starter
        self._built = (base, board, feed, log, history)
        self._probe = probe
        self._stop = threading.Event()
        self._wakes = threading.Event()
        self.runtime: Runtime | None = None

    def start(self) -> None:
        """Start the sampler and the loop of the running config, each ending when `stop` is called, and wake the loop
        for each setting `serve` writes."""
        base, board, feed, log, history = self._built
        self._stop = stop = threading.Event()
        self.runtime = start_scheduler(
            self._config,
            base,
            feed,
            board,
            history,
            log,
            self._config.level,
            stop,
            probe=self._probe,
            publish=publisher(log, feed),
            trajectories_response=self._trajectories_response,
            cached=self._cached,
            starter=self._starter,
        )
        follow_wakes(log, self._wake, stop)

    def _wake(self) -> None:
        runtime = self.runtime
        if runtime is None:
            return
        if runtime.loop is not None:
            runtime.loop.wake()
        runtime.push_status()

    def stop(self) -> None:
        self._stop.set()
        if self.runtime is not None and self.runtime.loop is not None:
            self.runtime.loop.wake()  # the loop looks at `stop` between events

    def reload(self, path: Path) -> None:
        """Re-read `path`. An invalid config is logged and the running one kept; a changed Scheduler block takes the
        runtime down and builds it again from the new config."""
        try:
            new = load(path)
        except (OSError, ValueError) as exc:
            logger.error("reload: %s: %s; keeping the running config", path, exc)
            return
        if scheduler_fixed_blocks(new) != scheduler_fixed_blocks(self._config):
            logger.warning("reload: the database or board changed; restart the worker to apply it")
        if scheduler_live_blocks(new) == scheduler_live_blocks(self._config):
            logger.info("reload: no Scheduler setting changed")
            return
        logger.info("reload: a Scheduler setting changed; rebuilding the runtime")
        self.stop()
        self._config = new
        self.start()


def main(
    argv: list[str] | None,
    parser: argparse.ArgumentParser,
    *,
    worker_board: Callable[..., tuple[Board, BoardFeed]],
    history_store: Callable[[Config, Path, Mapping[str, dict]], History],
    hold: Callable[[threading.Event, Callable[[], None]], None],
    trajectories_response: Callable[..., tuple[bytes, int]],
    cached: Callable[[Callable[[], dict[str, Any]], float], Callable[[], dict[str, Any]]],
    starter: Callable[..., Any],
) -> None:
    """Run the Scheduler worker; `runtime` passes the collaborators it builds, as no context imports it."""
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
        board, feed = worker_board(config, base, log, "starpulse-scheduler", stop)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    tasks = MachineTasks(feed, board.keys)
    follow(tasks, log, machine_events.STREAM, tasks.handle_entry)
    scheduler = Scheduler(
        config,
        base,
        board,
        feed,
        log,
        history_store(config, base, feed.machines),
        trajectories_response=trajectories_response,
        cached=cached,
        starter=starter,
    )
    scheduler.start()
    hold(stop, lambda: scheduler.reload(path))
    scheduler.stop()
