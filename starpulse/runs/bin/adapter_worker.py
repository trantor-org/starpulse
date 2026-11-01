"""`starpulse worker <dagu|github-actions|systemd|temporal>`: a run Adapter as its own process, which `serve` starts as a child for each `[[runs]]` instance that names it.

It follows each `[[runs]]` instance whose adapter names this worker (`starpulse.runs.opt_in`) and keeps the
workflows it reports in the event log (`starpulse.runs.projection`), where `serve` reads them for the page.
A source that offers its own push (Dagu's handlers, GitHub's `workflow_run` webhook) pushes through the ingest; this
worker reads the rest from the source. It beats into the log while it runs, so `serve` shows the page an instance whose
worker stopped. `SIGTERM` stops it; `SIGHUP` re-reads the config and, as the adapters are built once, only says whether
a restart is needed.
"""

from __future__ import annotations

import argparse
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.runs import opt_in
from starpulse.runs.bin.blocks import RunsConfig
from starpulse.runs.bin.runs_worker import reload
from starpulse.runs.projection import Publisher


def start(
    config: RunsConfig,
    path: Path | None,
    base: Path,
    log: EventLog,
    stop: threading.Event,
    *,
    load: Callable[[Path | None], RunsConfig],
    adapters: Any,
    worker_board: Callable[..., tuple[object, Any]],
) -> Callable[[], None]:
    """Follow each `(instance, adapter)` of `adapters` over `log` and beat for it until `stop` is set, and return the
    reload. Raises `ValueError` as `worker_board` does."""
    _, feed = worker_board(config, base, log, stop)
    publisher = Publisher(log)
    for instance, adapter in adapters:
        adapter.follow(instance.url, publisher.runs(instance.name, feed.runs(instance.name)), log)
        opt_in.keep_beating(log, instance.name, stop)
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
    stop = threading.Event()
    try:
        reload_config = start(config, path, base, log, stop, load=load, adapters=adapters, worker_board=worker_board)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    hold(stop, reload_config)
