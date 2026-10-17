"""`starpulse worker runs`: the Runs context (the run adapters, the trigger starts and the pushed-runs follower) as its
own process, beside `serve`.

It reads the config and the history database `serve` does and meets `serve` only in the event log: the workflows each
adapter reports are kept there (`starpulse._internal.runs.projection`) for the page, and the board events a trigger
matches arrive there as lane entries. What a restart must keep is in that log and the history store (a trigger's
cursor, the pushed runs, the learned step graphs), so a new process resumes where the last stopped and neither drops
nor repeats a run entry or a trigger start. `SIGTERM` stops it; `SIGHUP` re-reads the config and, as the adapters and
triggers are built once, only says whether a restart is needed.
"""

from __future__ import annotations

import argparse
import logging
import threading
from pathlib import Path

from starpulse._internal.board import replica
from starpulse._internal.config.config import Config, discover, load
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import database_url
from starpulse._internal.feed.board_feed import follow
from starpulse._internal.runs import run_events
from starpulse._internal.runs.projection import Publisher
from starpulse._internal.runs.push_runs import PUSHED_INSTANCE, PushRuns
from starpulse._internal.runs.triggers import run_triggers
from starpulse._internal.server.assembly import assemble, history_store
from starpulse._internal.server.hold import hold
from starpulse._internal.server.server import run_adapters, run_starts

logger = logging.getLogger(__name__)


def built_blocks(config: Config) -> tuple:
    """What of `config` the worker's adapters, triggers, board and history database were built from at start; a
    change needs a restart."""
    return (config.runs, config.triggers, config.database_url, config.board_type, config.board)


def reload(path: Path, config: Config) -> None:
    """Re-read `path`; an invalid config is logged, and a change to what the worker was built from asks for a restart."""
    try:
        new = load(path)
    except (OSError, ValueError) as exc:
        logger.error("reload: %s: %s; keeping the running config", path, exc)
        return
    if built_blocks(new) != built_blocks(config):
        logger.warning("reload: a runs, trigger, database or board setting changed; restart the worker to apply it")
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
    adapters = run_adapters(parser, config)
    starts = run_starts(adapters)
    try:
        board, feed = assemble(config, base, None, [])
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    log = EventLog(database_url(config.database_url, base))
    stop = threading.Event()
    replica.read(
        board, feed, "starpulse-runs", log, config, stop, local=args.local_board
    )
    store = history_store(config, base, feed.machines)
    publisher = Publisher(log)
    for instance, adapter in adapters:
        adapter.follow(instance.url, publisher.runs(instance.name, feed.runs(instance.name)), log)
    if config.triggers:
        threading.Thread(
            target=run_triggers,
            args=(config.triggers, starts, store, log, stop),
            kwargs={"replayed": feed.wait_replayed, "replay_head": feed.replay_head},
            name="board-triggers",
            daemon=True,
        ).start()
    # The learned step graphs persist only in StarPulse's own store.
    pushed = PushRuns(publisher.runs(PUSHED_INSTANCE, feed.runs(PUSHED_INSTANCE)), store)
    follow(pushed, log, run_events.STREAM, pushed.handle_entry, stop=stop)
    hold(stop, lambda: reload(path, config))
