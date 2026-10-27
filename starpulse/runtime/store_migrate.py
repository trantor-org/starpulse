"""`starpulse migrate --config FILE`: bring the store the config names to its schema, lane history and summaries.

Opening a store runs none of this (`HistoryStore` refuses one the chain has not reached), so a new or upgraded store is
migrated here before `serve` opens it. A second run finds the schema at the chain's head and writes nothing.
It prints one JSON line: `store` (the database URL, password hidden). The exit code is 2 for a flag the command does
not allow, a config that cannot be read, or a board the config does not assemble.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from starpulse.event_log.migrate import migrate
from starpulse.event_log.opening import database_url
from starpulse.flow_metrics.history import HistoryStore
from starpulse.runtime.assembly import assemble
from starpulse.runtime.config import ConfigError, discover, load

__all__ = ["main", "maintain"]


def main(argv: Sequence[str] | None = None) -> int:
    """Migrate the store the config names and repair its lanes and summaries; 0 once it is at the chain's head."""
    parser = argparse.ArgumentParser(prog="starpulse migrate", description="bring the store to its current schema")
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    args = parser.parse_args(argv)
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
    url = database_url(config.database_url, base)
    maintain(url, feed.machines, config.event_log_retention_days)
    print(json.dumps({"store": make_url(url).render_as_string(hide_password=True)}))
    return 0


def maintain(url: str, machines: Mapping[str, dict], retention_days: int | None) -> None:
    """The work `HistoryStore` used to do on every open: the schema, then the lane repair and the summaries it needs."""
    engine = create_engine(url)
    try:
        migrate(engine)
        store = HistoryStore(url, machines, engine, retention_days=retention_days)
        if store.repair_lanes():
            store.rebuild_summaries()
        store.build_summaries()
    finally:
        engine.dispose()
