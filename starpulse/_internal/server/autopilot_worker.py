"""`starpulse worker autopilot`: the Autopilot context (the capacity sampler and the dispatch loop) as its own process,
beside `serve`.

It reads the config and the history database `serve` does and meets `serve` only in the event log
(`starpulse._internal.autopilot.remote`): it publishes the status the page strip draws and wakes on the settings `serve`
writes. What a restart must keep (a task's one start, a harness's pause, the switch) is in that log, so a new process
resumes where the last stopped. `SIGTERM` stops it; `SIGHUP` re-reads the config and rebuilds the runtime in the same
process when an Autopilot setting changed.
"""

from __future__ import annotations

import argparse
import logging
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

from starpulse._internal.autopilot.remote import follow_wakes, publisher
from starpulse._internal.autopilot.runtime import Runtime
from starpulse._internal.board import replica
from starpulse._internal.board.seam import Board
from starpulse._internal.config.config import Config, discover, load
from starpulse._internal.eventlog import events as machine_events
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import History, database_url
from starpulse._internal.feed.board_feed import BoardFeed, follow
from starpulse._internal.feed.machine_tasks import MachineTasks
from starpulse._internal.server.assembly import assemble, history_store
from starpulse._internal.server.autopilot_service import start_autopilot
from starpulse._internal.server.hold import hold

logger = logging.getLogger(__name__)


def autopilot_blocks(config: Config) -> tuple:
    """What of `config` the runtime is built from; a change to anything else needs no rebuild."""
    return (config.autopilot, config.level, config.session_start_url)


def fixed_blocks(config: Config) -> tuple:
    """What of `config` the worker's board and history database were built from at start; a change needs a restart."""
    return (config.database_url, config.board_type, config.board)


class Autopilot:
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
    ) -> None:
        self._config = config
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
        self.runtime = start_autopilot(
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
        """Re-read `path`. An invalid config is logged and the running one kept; a changed Autopilot block takes the
        runtime down and builds it again from the new config."""
        try:
            new = load(path)
        except (OSError, ValueError) as exc:
            logger.error("reload: %s: %s; keeping the running config", path, exc)
            return
        if fixed_blocks(new) != fixed_blocks(self._config):
            logger.warning("reload: the database or board changed; restart the worker to apply it")
        if autopilot_blocks(new) == autopilot_blocks(self._config):
            logger.info("reload: no Autopilot setting changed")
            return
        logger.info("reload: an Autopilot setting changed; rebuilding the runtime")
        self.stop()
        self._config = new
        self.start()


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
    stop = threading.Event()
    replica.read(board, feed, "starpulse-autopilot", log, config, stop, local=args.local_board)
    tasks = MachineTasks(feed, board.keys)
    follow(tasks, log, machine_events.STREAM, tasks.handle_entry)
    autopilot = Autopilot(config, base, board, feed, log, history_store(config, base, feed.machines))
    autopilot.start()
    hold(stop, lambda: autopilot.reload(path))
    autopilot.stop()
