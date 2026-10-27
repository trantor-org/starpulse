"""`starpulse migrate --config FILE`: bring the store the config names to its schema, its one-time imports and summaries.

Opening a store runs none of this (`HistoryStore` refuses one the chain has not reached), so a new or upgraded store is
migrated here before `serve` opens it. Besides the schema and the summaries it moves the operator state once kept in
files (the scheduler switch, the history window, the run ledger) into the store, each once: the file is logged as
imported and renamed with `RETIRED_SUFFIX`, so a second run finds the schema at the chain's head and nothing to import.
It prints one JSON line: `store` (the database URL, password hidden). The exit code is 2 for a flag the command does
not allow, a config that cannot be read, or a board the config does not assemble.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, insert, select
from sqlalchemy.engine import make_url

from starpulse.board.adapters import history_window
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.migrate import migrate
from starpulse.event_log.opening import database_url
from starpulse.event_log.tables import scheduler_runs
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.runtime.assembly import assemble
from starpulse.runtime.config import ConfigError, discover, load
from starpulse.scheduler.model import ledger, toggle

__all__ = ["RETIRED_SUFFIX", "main", "maintain"]

logger = logging.getLogger(__name__)

#: What an imported file is renamed to, so the value it held can still be read by hand.
RETIRED_SUFFIX = ".imported"


def main(argv: Sequence[str] | None = None) -> int:
    """Migrate the store the config names, import its old files and build its summaries; 0 once it is at the head."""
    parser = argparse.ArgumentParser(prog="starpulse migrate", description="bring the store to its current schema")
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
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
    maintain(url, feed.machines, config.event_log_retention_days, base=base, state_dir=config.scheduler.state_dir)
    print(json.dumps({"store": make_url(url).render_as_string(hide_password=True)}))
    return 0


def maintain(
    url: str,
    machines: Mapping[str, dict],
    retention_days: int | None,
    *,
    base: Path | None = None,
    state_dir: str | None = None,
) -> None:
    """The work `HistoryStore` used to do on every open: the schema, then the summaries it needs.

    With a `base` (the config's directory) it also imports the operator files found there, and in `state_dir` under it.
    """
    engine = create_engine(url)
    try:
        migrate(engine)
        if base is not None:
            import_files(EventLog(url, engine=engine), base, base / (state_dir or ""))
        HistoryStore(url, machines, engine, retention_days=retention_days).build_summaries()
    finally:
        engine.dispose()


def import_files(log: EventLog, base: Path, state_dir: Path) -> None:
    """Move the files that held operator state before it lived in the store into it, each once, then retire them.

    A setting a store already holds wins over its file, and a store that already holds runs ignores the ledger file; the
    file is retired either way, so an old one cannot come back after a reset.
    """
    _import_setting(log, toggle.KEY, state_dir / toggle.TOGGLE_FILE, "enabled")
    _import_setting(log, history_window.KEY, base / history_window.SETTINGS_FILE, "history_hours")
    _import_runs(log.engine, state_dir / ledger.LEDGER_FILE)


def _import_setting(log: EventLog, key: str, file: Path, field: str) -> None:
    try:
        text = file.read_text()
        written = file.stat().st_mtime
    except FileNotFoundError:
        return
    try:
        value: Any = json.loads(text)[field]
    except ValueError, KeyError, TypeError:
        value = None
    if value is not None and log.setting(key) is None:
        log.set_setting(key, value, updated_at=written)
        logger.info("migrate: imported %s from %s", key, file)
    _retire(file)


def _import_runs(engine: Engine, file: Path) -> None:
    try:
        text = file.read_text()
        written = file.stat().st_mtime
    except FileNotFoundError:
        return
    rows = [{**json.loads(line), "recorded_at": written} for line in text.splitlines() if line.strip()]
    with engine.begin() as db:
        if rows and db.execute(select(scheduler_runs.c.id).limit(1)).first() is None:
            db.execute(insert(scheduler_runs), rows)
            logger.info("migrate: imported %d scheduler runs from %s", len(rows), file)
    _retire(file)


def _retire(file: Path) -> None:
    try:
        file.replace(file.with_name(file.name + RETIRED_SUFFIX))
    except OSError as exc:
        logger.warning("migrate: retiring %s failed: %s", file, exc)
