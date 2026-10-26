"""`starpulse worker flow-metrics`: the Flow Metrics context (the recorder that copies the event log's machine events into the
history store, and the hourly prune of the event log) as its own process, beside `serve`.

It reads the config and the history database `serve` does and meets `serve` only in the database: the page reads the
history this worker writes. The two threads run together because both write that database: a prune beside a recorder
that is behind archives rows the recorder has not read. The recorder's cursor is saved with each row in one
transaction (`HistoryStore.record_machine`), so a new process resumes after the last event the store holds and neither
drops nor repeats a history row. `SIGTERM` stops it; `SIGHUP` re-reads the config and, as the threads are built once,
only says whether a restart is needed.
"""

from __future__ import annotations

import argparse
import logging
import threading
from pathlib import Path

from starpulse.runtime.blocks import flow_metrics_built_blocks
from starpulse._internal.config.config import Config, discover, load
from starpulse.runtime.assembly import assemble, history_store, keep_event_log
from starpulse.runtime.hold import hold
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.flow_metrics.history import record_machine_events

logger = logging.getLogger(__name__)


def reload(path: Path, config: Config) -> None:
    """Re-read `path`; an invalid config is logged, and a change to what the worker was built from asks for a restart."""
    try:
        new = load(path)
    except (OSError, ValueError) as exc:
        logger.error("reload: %s: %s; keeping the running config", path, exc)
        return
    if flow_metrics_built_blocks(new) != flow_metrics_built_blocks(config):
        logger.warning("reload: a database, board or event log setting changed; restart the worker to apply it")
    else:
        logger.info("reload: no History setting changed")


def main(argv: list[str] | None, parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")
    base = args.config.parent if args.config else Path.cwd()
    try:
        _, feed = assemble(config, base, None, [])
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    log = EventLog(database_url(config.database_url, base))
    store = history_store(config, base, feed.machines)
    stop = threading.Event()
    keep_event_log(log, config, base, stop=stop)
    threading.Thread(target=record_machine_events, args=(store, log, stop), name="machine-history", daemon=True).start()
    hold(stop, lambda: reload(path, config))
