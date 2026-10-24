"""`starpulse worker runs`: the Runs context (the run adapters no opt-in worker runs, and the pushed-runs follower) as its own process, beside
`serve`.

It reads the config and the history database `serve` does and meets `serve` only in the event log: the workflows each
adapter reports are kept there (`starpulse._internal.runs.projection`) for the page. What a restart must keep is in
that log and the history store (the pushed runs, the learned step graphs), so a new process resumes where the last
stopped and drops or repeats no run entry. `SIGTERM` stops it; `SIGHUP` re-reads the config and, as the adapters are
built once, only says whether a restart is needed.
"""

from __future__ import annotations

import argparse
import logging
import threading
from pathlib import Path

from starpulse._internal.config.config import Config, discover, load
from starpulse._internal.eventlog.history import database_url
from starpulse._internal.feed.board_feed import follow
from starpulse._internal.runs import opt_in, run_events
from starpulse._internal.runs.projection import Publisher
from starpulse._internal.runs.push_runs import PUSHED_INSTANCE, PushRuns
from starpulse._internal.runs.run_streams import RunStreams, record_run_streams
from starpulse._internal.server.assembly import history_store, worker_board
from starpulse._internal.server.hold import hold
from starpulse._internal.server.server import run_adapters
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.store import EventStore

logger = logging.getLogger(__name__)


def built_blocks(config: Config) -> tuple:
    """What of `config` the worker's adapters, board and history database were built from at start; a
    change needs a restart."""
    return (config.runs, config.database_url, config.board_type, config.board)


def reload(path: Path, config: Config) -> None:
    """Re-read `path`; an invalid config is logged, and a change to what the worker was built from asks for a restart."""
    try:
        new = load(path)
    except (OSError, ValueError) as exc:
        logger.error("reload: %s: %s; keeping the running config", path, exc)
        return
    if built_blocks(new) != built_blocks(config):
        logger.warning("reload: a runs, database or board setting changed; restart the worker to apply it")
    else:
        logger.info("reload: no Runs setting changed")


def main(argv: list[str] | None, parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")
    base = args.config.parent if args.config else Path.cwd()
    adapters = opt_in.followed_by(run_adapters(parser, config), None)
    log = EventLog(database_url(config.database_url, base))
    stop = threading.Event()
    try:
        _, feed = worker_board(config, base, log, "starpulse-runs", stop)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    store = history_store(config, base, feed.machines)
    publisher = Publisher(log)
    for instance, adapter in adapters:
        adapter.follow(instance.url, publisher.runs(instance.name, feed.runs(instance.name)), log)
    # The learned step graphs persist only in StarPulse's own store.
    pushed = PushRuns(publisher.runs(PUSHED_INSTANCE, feed.runs(PUSHED_INSTANCE)), store)
    follow(pushed, log, run_events.STREAM, pushed.handle_entry, stop=stop)
    # Every entry path's run entries also land in the event store, one stream per run.
    streams = RunStreams(EventStore(log.engine))
    threading.Thread(target=record_run_streams, args=(streams, log, stop), daemon=True).start()
    hold(stop, lambda: reload(path, config))
