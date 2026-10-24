"""`starpulse worker <dagu|github-actions|systemd>`: a run Adapter as its own process, which an operator opts into and `serve` never starts.

It follows each `[[runs]]` instance whose adapter names this worker (`starpulse._internal.runs.opt_in`) and keeps the
workflows it reports in the event log (`starpulse._internal.runs.projection`), where `serve` reads them for the page.
A source that offers its own push (Dagu's handlers, GitHub's `workflow_run` webhook) pushes through the ingest; this
worker reads the rest from the source. It beats into the log while it runs, so `serve` shows the page an instance whose
worker stopped. `SIGTERM` stops it; `SIGHUP` re-reads the config and, as the adapters are built once, only says whether
a restart is needed.
"""

from __future__ import annotations

import argparse
import threading
from pathlib import Path

from starpulse._internal.config.config import discover, load
from starpulse._internal.eventlog.history import database_url
from starpulse._internal.runs import opt_in
from starpulse._internal.runs.projection import Publisher
from starpulse._internal.server.assembly import worker_board
from starpulse._internal.server.hold import hold
from starpulse._internal.server.runs_worker import reload
from starpulse._internal.server.server import run_adapters
from starpulse.event_log.event_log import EventLog


def main(argv: list[str] | None, parser: argparse.ArgumentParser, context: str) -> None:
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
        _, feed = worker_board(config, base, log, f"starpulse-{context}", stop)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    publisher = Publisher(log)
    for instance, adapter in adapters:
        adapter.follow(instance.url, publisher.runs(instance.name, feed.runs(instance.name)), log)
        opt_in.keep_beating(log, instance.name, stop)
    hold(stop, lambda: reload(path, config))
