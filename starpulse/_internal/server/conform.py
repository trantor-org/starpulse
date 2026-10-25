"""`starpulse conform`: replay the recorded history against the machines the project declares.

    starpulse conform --config starpulse.toml [--since WHEN] [--machine NAME ...]

The board's lane changes are replayed on its `board` machine and every other machine's recorded events on the machine
of that name, each task or run from the initial state (`starpulse.machine_engine.model.replay`). A guard that reads a
task's facts is not judged: the history keeps none. It prints one JSON document: `machines` (each `machine`, the
`replayed` moves and its `violations`, each a `source`, the `move` made from it, a `count` and example `tasks`),
`replayed` and `violations` in total. The exit code is 0 for a history the machines allow, 1 when a move is a violation
and 2 for a flag the command does not allow, a `--machine` the project does not declare, a config that cannot be read
or a board the config does not assemble.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from starpulse._internal.config.config import ConfigError, discover, load
from starpulse._internal.server.assembly import assemble, history_store
from starpulse.flow_metrics.history import HistoryStore
from starpulse.machine_engine.model import replay

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Replay the history; 0 when every machine allows it, 1 when a move is a violation."""
    parser = argparse.ArgumentParser(
        prog="starpulse conform", description="replay the recorded history against the machines the project declares"
    )
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    parser.add_argument("--since", help="replay only moves at or after this ISO date or epoch seconds")
    parser.add_argument(
        "--machine", action="append", default=[], metavar="NAME", help="replay only this machine (repeatable)"
    )
    args = parser.parse_args(argv)
    since = _since(parser, args.since)
    path = discover(args.config)
    try:
        config = load(path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    base = path.parent if path else Path.cwd()
    try:
        _, feed = assemble(config, base, None, [])
    except (OSError, ValueError) as exc:
        parser.error(f"the board does not assemble: {exc}")
    if unknown := [name for name in args.machine if name not in feed.machines]:
        parser.error(f"no such machine: {', '.join(unknown)}; declared: {', '.join(sorted(feed.machines))}")
    store = history_store(config, base, feed.machines)
    reports = [
        _check(store, name, machine, since)
        for name, machine in feed.machines.items()
        if name in (args.machine or feed.machines)
    ]
    reports = [report for report in reports if report.replayed]
    violations = sum(v.count for report in reports for v in report.violations)
    print(
        json.dumps(
            {
                "machines": [asdict(report) for report in reports],
                "replayed": sum(report.replayed for report in reports),
                "violations": violations,
            }
        )
    )
    return int(violations > 0)


def _check(store: HistoryStore, name: str, machine: dict, since: float | None) -> replay.Report:
    """The machine's history judged: the board's lane changes, or the events recorded on the machine of that name."""
    if name == "board":
        return replay.check_lanes(name, machine, store.lane_rows(since))
    rows = [(key, at, event) for flow, key, at, event in store.machine_event_rows(since) if flow == name]
    return replay.check_events(name, machine, rows)


def _since(parser: argparse.ArgumentParser, value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        parser.error(f"--since {value!r} is neither epoch seconds nor an ISO date")
