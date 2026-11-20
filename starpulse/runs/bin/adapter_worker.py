"""`starpulse worker <github-actions|systemd|woodpecker>`: a run Adapter as its own process, which `serve` starts as a child for each `[[runs]]` instance that names it.

It announces its process id in the event log. `SIGTERM` stops it and marks the announced process as ending, so its exit reads as a stop; `SIGHUP` re-reads the config.
"""

import argparse
import logging
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.event_log.wake import StopEvent
from starpulse.runs.application.queries.projection import Publisher
from starpulse.runs.bin.blocks import RunsConfig
from starpulse.runs.bin.runs_worker import reload
from starpulse.runs.model import opt_in

logger = logging.getLogger(__name__)


def _ending(log: EventLog, name: str) -> None:
    try:
        opt_in.announce(log, name, ending=True)
    except Exception:  # a failed write never aborts the stop that called it
        logger.warning("%s: cannot mark the worker as ending", name, exc_info=True)


def start(
    config: RunsConfig,
    path: Path | None,
    base: Path,
    log: EventLog,
    stop: StopEvent,
    *,
    load: Callable[[Path | None], RunsConfig],
    adapters: Any,
    worker_board: Callable[..., tuple[object, Any]],
) -> Callable[[], None]:
    """Follow each `(instance, adapter)` of `adapters` over `log`, announce this process for it, and return the
    reload. Raises `ValueError` as `worker_board` does."""
    _, feed = worker_board(config, base, log, stop)
    publisher = Publisher(log)
    for instance, adapter in adapters:
        adapter.follow(instance.url, publisher.runs(instance.name, feed.runs(instance.name)), log)
        opt_in.announce(log, instance.name)
        ending = partial(_ending, log, instance.name)
        stop.listen(ending)
        if stop.is_set():
            ending()
    return lambda: reload(path, config, load)


def main(
    argv: list[str] | None,
    parser: argparse.ArgumentParser,
    context: str,
    *,
    discover: Callable[[Path | None], Path | None],
    load: Callable[[Path | None], RunsConfig],
    run_adapters: Callable[[argparse.ArgumentParser, RunsConfig], Any],
    worker_board: Callable[..., tuple[object, Any]],
    hold: Callable[[threading.Event, Callable[[], None]], None],
) -> None:
    """Run one opt-in Adapter worker; `runtime` passes the collaborators it builds, as no context imports it."""
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")
    base = args.config.parent if args.config else Path.cwd()
    adapters = opt_in.followed_by(run_adapters(parser, config), context)
    log = EventLog(database_url(config.database_url, base))
    stop = StopEvent()
    try:
        reload_config = start(config, path, base, log, stop, load=load, adapters=adapters, worker_board=worker_board)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    hold(stop, reload_config)
