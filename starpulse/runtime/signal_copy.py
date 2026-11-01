"""`starpulse copy-signals [--days N]`: the signals Loki holds into `starpulse_signals`, each key once.

Until the adapters write the table, a signal lives in Loki's `starpulse-signals` stream. This copies the last `--days`
(default 8) of signals, by signal time, that the table lacks; a rerun finds every key present and inserts nothing. The
summary is one JSON line on stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
from pathlib import Path

from starpulse.event_log.opening import open_event_log
from starpulse.harness_telemetry.adapters.inbound.telemetry import KEEP_S
from starpulse.harness_telemetry.adapters.outbound.loki import LokiSignals
from starpulse.harness_telemetry.adapters.outbound.signal_table import SignalTable
from starpulse.runtime.config import ConfigError, discover, load

__all__ = ["copy_signals", "main"]


def copy_signals(loki: LokiSignals, table: SignalTable, since: float) -> int:
    """Inserts the signals Loki holds with a `time` from `since` (epoch seconds) on that `table` lacks, a page at a
    time; returns how many. Loki stamps a line with its push time, so the fetch starts at the window's first stamp and
    the signal's own time drops what a replayed export pushed late."""
    copied = 0
    for page in loki.pages(int(since * 1e9)):
        copied += table.insert(row for _, row in page if row["time"] >= since)
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starpulse copy-signals", description=__doc__)
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
        print("starpulse copy-signals: the config sets no telemetry_loki_url", file=sys.stderr)
        return 1
    try:
        copied = copy_signals(LokiSignals(config.telemetry_loki_url), SignalTable(log.engine), time.time() - args.days * 86400)
    except (OSError, urllib.error.URLError) as exc:
        print(f"starpulse copy-signals: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"days": args.days, "copied": copied}))
    return 0
