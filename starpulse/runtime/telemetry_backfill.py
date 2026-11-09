"""`starpulse backfill-telemetry [--days N]`: the event log's `telemetry:signals` rows into Loki, each key once.

Before `telemetry_loki_url` was set the signals went to the event log, so the analytics views, which read only Loki,
saw a history shorter than their 168 h window. This copies the last `--days` (default 8) of signals the log holds and
Loki lacks; Loki stamps a line with its push time, so the serving process reads the copies on its next poll and drops
a repeated key. A rerun finds every key present and pushes nothing. The summary is one JSON line on stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
from pathlib import Path

from starpulse.event_log.event_log import EventLog, Tail
from starpulse.event_log.opening import open_event_log
from starpulse.harness_telemetry.adapters.inbound.telemetry import KEEP_S, TelemetryLog
from starpulse.harness_telemetry.adapters.outbound.loki import LokiSignals
from starpulse.runtime.config import ConfigError, discover, load

__all__ = ["backfill", "main"]

BATCH = 1000
PAUSE_S = 2.0  # what a push waits after Loki's ingestion rate limit (429) refuses it, a whole batch at a time
RETRIES = 30


def push(loki: LokiSignals, rows: list[dict], pause: float) -> None:
    """Pushes `rows`, retrying a 429 `RETRIES` times `pause` seconds apart; any other fault raises."""
    for attempt in range(RETRIES + 1):
        try:
            return loki.push(rows)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == RETRIES:
                raise
            time.sleep(pause)


def backfill(log: EventLog, loki: LokiSignals, since: float, pause: float = PAUSE_S) -> int:
    """Pushes the signals of the log from `since` (epoch seconds) on that Loki lacks; returns how many."""
    present = {row["key"] for _, row in loki.fetch(int(since * 1e9))}
    tail = Tail.replay(log, TelemetryLog.STREAM, batch=5000)
    pending: list[dict] = []
    pushed = 0
    while entries := tail.poll():
        for entry in entries:
            row = entry.fields
            if row["time"] >= since and row["key"] not in present:
                present.add(row["key"])
                pending.append(row)
        while len(pending) >= BATCH:
            push(loki, pending[:BATCH], pause)
            pushed += BATCH
            pending = pending[BATCH:]
    push(loki, pending, pause)
    return pushed + len(pending)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starpulse backfill-telemetry", description=__doc__)
    parser.add_argument("--days", type=float, default=KEEP_S / 86400, help="days of signals to copy (default 8)")
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
        log = open_event_log(config.database_url, path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    if not config.telemetry_loki_url:
        print("starpulse backfill-telemetry: the config sets no telemetry_loki_url", file=sys.stderr)
        return 1
    try:
        pushed = backfill(log, LokiSignals(config.telemetry_loki_url), time.time() - args.days * 86400)
    except OSError as exc:
        print(f"starpulse backfill-telemetry: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"days": args.days, "pushed": pushed}))
    return 0
