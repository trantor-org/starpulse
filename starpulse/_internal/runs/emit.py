"""`starpulse emit StepStarted|StepFinished`: append a workflow run, or one of its steps, to the event log.

Deprecated in 0.4 and gone in 0.5: it builds the Step CloudEvent a producer would post to `POST /api/machine-events`
and writes it through the same ingest, in this process, as the producer `local`; it prints that notice to stderr.

    python -m starpulse emit StepStarted --workflow nightly --run 2026-10-03 --status running
    python -m starpulse emit StepFinished --workflow nightly --run 2026-10-03 --status succeeded --step load --depends fetch,clean

A scheduler hook (cron, systemd, Cronicle, Rundeck, an Airflow callback) calls it at each start and end. A step's
entries name the step and, optionally, the steps it waits on; a workflow no adapter lists draws the step graph those
entries add up to. The log is in the database `--config` names (default `starpulse.toml` in the working directory,
as `serve` finds it), so a hook that runs from no fixed directory passes `--config`. The exit code is 1 when the log
refused the entry and 2 for a flag the contract does not allow or a config that cannot be read.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import get_args

from starpulse._internal.config.config import Producer
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import open_event_log
from starpulse._internal.runs import run_events
from starpulse._internal.runs.cloudevents import CloudEventsIngest
from starpulse._internal.runs.ingest import cloudevent
from starpulse.contracts.adapters import RunStatus

DEPRECATED = (
    "starpulse emit is deprecated and goes in 0.5: post the Step CloudEvent to the server's /api/machine-events "
    "(docs/serving.md)"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="starpulse emit", description="push a workflow run, or one of its steps, onto the event log"
    )
    parser.add_argument("event", choices=run_events.EVENTS)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run", required=True, help="the run's id")
    parser.add_argument("--status", required=True, choices=get_args(RunStatus))
    parser.add_argument("--step", help="report this step of the run instead of the run itself")
    parser.add_argument("--depends", help="with --step: comma-separated names of the steps it waits on")
    parser.add_argument(
        "--config",
        type=Path,
        help="the TOML config whose database holds the event log; default starpulse.toml when it exists",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    now: Callable[[], float] = time.time,
    log: EventLog | None = None,
) -> int:
    """Append one entry; 0 when the log took it, 1 when it refused."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.depends and not args.step:
        parser.error("--depends needs --step")
    depends = [name for name in (args.depends or "").split(",") if name]
    if log is None:
        try:
            log = open_event_log(args.config)
        except (OSError, ValueError) as exc:
            parser.error(f"{args.config or 'starpulse.toml'}: {exc}")
    print(DEPRECATED, file=sys.stderr)
    local = Producer(run_events.LOCAL, "", (), ())
    ingest = CloudEventsIngest({local.name: local}, {}, log, {})
    event = {"event": args.event, "run_id": args.run, "status": args.status, "time": now()}
    sent = cloudevent(event | {"step": args.step, "depends": depends}, local.name, args.workflow)
    status, answer = ingest.write(local.name, [sent])
    if status == 503:
        print(f"starpulse emit: {run_events.STREAM} refused the entry (is the database reachable?)", file=sys.stderr)
        return 1
    if status != 201:
        parser.error(answer["error"])
    return 0
