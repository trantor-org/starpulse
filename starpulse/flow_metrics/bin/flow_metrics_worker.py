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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore, record_machine_events, record_verdicts
from starpulse.flow_metrics.bin.blocks import FlowMetricsConfig, flow_metrics_built_blocks

logger = logging.getLogger(__name__)


class Feed(Protocol):
    """The board feed as far as this worker reads it."""

    machines: Mapping[str, dict]


def reload(path: Path, config: FlowMetricsConfig, load: Callable[[Path | None], FlowMetricsConfig]) -> None:
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


def start(
    config: FlowMetricsConfig,
    path: Path | None,
    base: Path,
    log: EventLog,
    stop: threading.Event,
    *,
    load: Callable[[Path | None], FlowMetricsConfig],
    assemble: Callable[..., tuple[object, Feed]],
    history_store: Callable[[FlowMetricsConfig, Path, Mapping[str, dict]], HistoryStore],
    keep_event_log: Callable[..., object],
) -> Callable[[], None]:
    """Start the History recorders and the event log prune over `log`, each ending when `stop` is set, and return their
    reload. Raises `ValueError` as `assemble` does."""
    _, feed = assemble(config, base, None, [])
    store = history_store(config, base, feed.machines)
    keep_event_log(log, config, base, stop=stop)
    threading.Thread(target=record_machine_events, args=(store, log, stop), name="machine-history", daemon=True).start()
    threading.Thread(target=record_verdicts, args=(store, log, stop), name="verdict-history", daemon=True).start()
    return lambda: reload(path, config, load)


def main(
    argv: list[str] | None,
    parser: argparse.ArgumentParser,
    *,
    discover: Callable[[Path | None], Path | None],
    load: Callable[[Path | None], FlowMetricsConfig],
    assemble: Callable[..., tuple[object, Feed]],
    history_store: Callable[[FlowMetricsConfig, Path, Mapping[str, dict]], HistoryStore],
    keep_event_log: Callable[..., object],
    hold: Callable[[threading.Event, Callable[[], None]], None],
) -> None:
    """Run the History recorder; `runtime` passes the collaborators it builds, as no context imports it."""
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
            assemble=assemble,
            history_store=history_store,
            keep_event_log=keep_event_log,
        )
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    hold(stop, reload_config)
