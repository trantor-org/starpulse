"""`starpulse emit start|end`: push a workflow run, or one of its steps, onto the runs stream.

    python -m starpulse emit start --workflow nightly --run 2026-10-03 --status running
    python -m starpulse emit end   --workflow nightly --run 2026-10-03 --status succeeded --step load --depends fetch,clean

A scheduler hook (cron, systemd, Cronicle, Rundeck, an Airflow callback) calls it at each start and end. A step's
entries name the step and, optionally, the steps it waits on; a workflow no adapter lists draws the step graph those
entries add up to. Redis is `REDIS_URL`, else `RUNS_REDIS_HOST`/`_PORT` with `REDIS_PASSWORD`. The exit code is 1
when the stream refused the entry and 2 for a flag the contract does not allow.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, get_args

from starpulse import run_events
from starpulse.contracts import RunStatus


class Producer(Protocol):
    def emit(self, fields: dict[str, Any]) -> str | None: ...


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="starpulse emit", description="push a workflow run, or one of its steps, onto the runs stream"
    )
    parser.add_argument("phase", choices=run_events.PHASES)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run", required=True, help="the run's id")
    parser.add_argument("--status", required=True, choices=get_args(RunStatus))
    parser.add_argument("--step", help="report this step of the run instead of the run itself")
    parser.add_argument("--depends", help="with --step: comma-separated names of the steps it waits on")
    return parser


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] = os.environ,
    *,
    now: Callable[[], float] = time.time,
    producer: Producer | None = None,
) -> int:
    """Publish one entry; 0 when the stream took it, 1 when it refused."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.depends and not args.step:
        parser.error("--depends needs --step")
    depends = [name for name in (args.depends or "").split(",") if name]
    event = run_events.entry(
        args.phase, args.workflow, args.run, args.status, now=now(), step=args.step, depends=depends
    )
    if (producer or run_events.producer(environ)).emit(event) is None:
        print(f"starpulse emit: {run_events.STREAM} refused the entry (is Redis reachable?)", file=sys.stderr)
        return 1
    return 0
