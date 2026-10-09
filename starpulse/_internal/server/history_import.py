"""`starpulse import-history FILE`: add a board's earlier lane changes to the store the config names, once each.

    starpulse import-history lanes.jsonl --config starpulse.toml

`FILE` is JSON Lines (`starpulse._internal.eventlog.lane_import`): one `{event_id, task, lane, time}` change per line.
The store is the one `serve` opens, so its board's machines place each change, and the store's lane history is repaired
and its summaries rebuilt afterwards. It prints one JSON line: `source`, `store` (the database URL, password hidden),
`read`, `imported` (the changes the store holds afterwards that it did not before: 0 on a second run) and
`summary_differences` (empty when the rebuilt summaries match the raw rows). The exit code is 1 for a file with a line
that is not a change and 2 for a flag the command does not allow, a file or config that cannot be read, or a board
the config does not assemble. Stop `serve` first: a row it records while the summaries rebuild is missing from them.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from starpulse._internal.config.config import ConfigError, discover, load
from starpulse._internal.eventlog import lane_import
from starpulse._internal.server.server import assemble, history_store

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Import the file's changes; 0 when the store holds them, 1 for a line that is not a change."""
    parser = argparse.ArgumentParser(
        prog="starpulse import-history", description="add a board's earlier lane changes to the store, once each"
    )
    parser.add_argument("source", type=Path, help="the JSONL file: one `{event_id, task, lane, time}` object per line")
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    try:
        changes = lane_import.read(args.source)
    except OSError as exc:
        parser.error(str(exc))
    except ValueError as exc:
        print(f"starpulse import-history: {exc}", file=sys.stderr)
        return 1
    base = path.parent if path else Path.cwd()
    try:
        _, feed = assemble(config, base, None, [])
    except (OSError, ValueError) as exc:
        parser.error(f"the board does not assemble: {exc}")
    store = history_store(config, base, feed.machines)
    imported = store.import_lanes(changes)
    print(
        json.dumps(
            {
                "source": str(args.source),
                "store": store.engine.url.render_as_string(hide_password=True),
                "read": len(changes),
                "imported": imported,
                "summary_differences": store.summary_differences(),
            }
        )
    )
    return 0
