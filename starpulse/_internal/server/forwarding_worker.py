"""`starpulse worker forwarding`: the Forwarding context (the forwarder that sends the event log to the hub) as its own
process, beside `serve`.

It reads the config and the history database `serve` does and meets `serve` only in the event log: the forwarder's
opt-in is a setting there that `PUT /api/forwarding` writes and the forwarder reads before every batch, and what the
forwarder learned of the hub is kept there (`starpulse._internal.hub.forward_report`) for the page. Its cursor is in the
history store, saved after each acknowledged batch, so a new process resumes after the last event the hub took and
neither drops nor repeats a forwarded event. `SIGTERM` stops it; `SIGHUP` re-reads the config and, as the forwarder is
built once, only says whether a restart is needed.
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
from pathlib import Path

from starpulse._internal.config.config import Config, discover, load
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import database_url
from starpulse._internal.hub import forward
from starpulse._internal.hub.forward_report import Publisher
from starpulse._internal.server.assembly import assemble, history_store
from starpulse._internal.server.hold import hold

logger = logging.getLogger(__name__)


def built_blocks(config: Config) -> tuple:
    """What of `config` the worker's forwarder and database were built from at start; a change needs a restart."""
    return (config.forward, config.database_url)


def reload(path: Path, config: Config) -> None:
    """Re-read `path`; an invalid config is logged, and a change to what the worker was built from asks for a restart."""
    try:
        new = load(path)
    except (OSError, ValueError) as exc:
        logger.error("reload: %s: %s; keeping the running config", path, exc)
        return
    if built_blocks(new) != built_blocks(config):
        logger.warning("reload: a forward or database setting changed; restart the worker to apply it")
    else:
        logger.info("reload: no Forwarding setting changed")


def main(argv: list[str] | None, parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")
    if config.forward is None:
        parser.exit(1, f"{path}: no [forward] table; the forwarding worker has nothing to send\n")
    base = args.config.parent if args.config else Path.cwd()
    log = EventLog(database_url(config.database_url, base))
    try:
        _, feed = assemble(config, base, None, [])
        forwarder = forward.build(config, base, log, history_store(config, base, feed.machines), os.environ)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    stop = threading.Event()
    forward.start(forwarder, stop, Publisher(log, forwarder))
    hold(stop, lambda: reload(path, config))
