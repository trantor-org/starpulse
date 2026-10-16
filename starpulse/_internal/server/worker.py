"""`starpulse worker pulls`: the Delivery context (the pull request store's sync and projection, the task actor and the
release of dependents) as its own process, beside `serve`.

It reads the config and the history database `serve` does and meets `serve` only in the event log
(`starpulse._internal.pulls.delivery`): it keeps the pull request projection there, takes the refreshes a page asked and
relays the actor's notes and metrics. `SIGTERM` stops it; `SIGHUP` re-reads the config.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from starpulse._internal.config.config import Config, discover, load
from starpulse._internal.config.pins import GitHub
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import database_url
from starpulse._internal.pulls.delivery import (
    NotingFeed,
    Publisher,
    follow_refreshes,
    keep_metrics,
)
from starpulse._internal.pulls.pulls import PullStore
from starpulse._internal.server.server import assemble, start_delivery

logger = logging.getLogger(__name__)

CONTEXTS = ("pulls",)


def delivery_blocks(config: Config) -> tuple:
    """What of `config` the Delivery context is built from; a change to anything else needs no rebuild."""
    return (
        config.database_url,
        config.task_actor,
        config.release,
        config.repos,
        config.pull_requests,
        config.ci,
        config.board,
    )


def reload_config(path: Path, running: Config) -> None:
    """Re-read `path`. An invalid config is logged and the running one kept; a changed Delivery block restarts the loops
    by re-executing this command in place (same process and unit, a fresh interpreter), as a thread of the loops cannot be
    taken down and rebuilt in one."""
    try:
        new = load(path)
    except (OSError, ValueError) as exc:
        logger.error("reload: %s: %s; keeping the running config", path, exc)
        return
    if delivery_blocks(new) == delivery_blocks(running):
        logger.info("reload: no Delivery setting changed")
        return
    logger.info("reload: a Delivery setting changed; restarting the loops in place")
    os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])


def hold(stop: threading.Event, reload: Callable[[], None]) -> None:  # pragma: no mutate block — process boundary
    """Block until `SIGTERM`, running `reload` on `SIGHUP`."""
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGHUP, lambda *_: reload())
    stop.wait()


def worker_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="starpulse worker", description=__doc__.splitlines()[0])
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
    pulls = PullStore(log.engine)
    pins = GitHub(lambda: feed.pull_answers().get("pins", {}))
    try:
        actor, sync = start_delivery(
            config,
            board,
            feed,
            log,
            pulls,
            pins,
            stop,
            actor_feed=NotingFeed(feed, log),
            after_project=Publisher(log, feed).publish,
        )
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    if sync:
        follow_refreshes(log, sync.request, stop)
    if actor:
        keep_metrics(log, actor.exposition, stop)
    hold(stop, lambda: reload_config(path, config))
