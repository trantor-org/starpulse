"""`starpulse migrate --config FILE`: bring the store the config names to its schema, its one-time imports and summaries.

Opening a store runs none of this (`HistoryStore` refuses one the chain has not reached), so a new or upgraded store is
migrated here before `serve` opens it. Besides the schema and the summaries it moves the operator state once kept in
files (the scheduler switch, the history window, the run ledger) into the store, each once: the file is logged as
imported and renamed with `RETIRED_SUFFIX`, so a second run finds the schema at the chain's head and nothing to import.
It prints one JSON line: `store` (the database URL, password hidden). The exit code is 2 for a flag the command does
not allow, a config that cannot be read, or a board the config does not assemble.
"""

import argparse
import glob
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from starpulse.contracts.adapters import TaskKeys
lazy from sqlalchemy import insert, select
lazy from sqlalchemy.engine import make_url

lazy from starpulse.board.adapters import history_window
lazy from starpulse.event_log.event_log import EventLog, store_engine
lazy from starpulse.event_log.migrate import migrate, settled as at_head
lazy from starpulse.event_log.opening import database_url
lazy from starpulse.event_log.readmodel.projector import Projector
lazy from starpulse.event_log.readmodel.snapshot_store import build as build_snapshots
lazy from starpulse.event_log.readmodel.snapshot_store import built as snapshots_built
lazy from starpulse.event_log.store import EventStore
lazy from starpulse.event_log.tables import scheduler_runs
lazy from starpulse.github.adapters.outbound.carry_over import carry_over
lazy from starpulse.runtime.assembly import declared
lazy from starpulse.runtime.config import ConfigError, discover, load
lazy from starpulse.scheduler.model import ledger, toggle

__all__ = ["RETIRED_SUFFIX", "main", "maintain", "settled"]

logger = logging.getLogger(__name__)

#: What an imported file is renamed to, so the value it held can still be read by hand.
RETIRED_SUFFIX = ".imported"
#: The setting that records the old inbox file carried into the store, so a second run copies nothing.
INBOX_CARRIED = "github_inbox_carried"


def main(argv: Sequence[str] | None = None) -> int:
    """Migrate the store the config names, import its old files and build its summaries; 0 once it is at the head.

    With `--check` it migrates nothing and exits 0 when `settled`, else 1.
    """
    parser = argparse.ArgumentParser(prog="starpulse migrate", description="bring the store to its current schema")
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    parser.add_argument("--check", action="store_true", help="migrate nothing: exit 0 when the store needs no migrate, else 1")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    path = discover(args.config)
    try:
        config = load(path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    base = path.parent if path else Path.cwd()
    try:
        board, machines, *_ = declared(config, base)
    except (OSError, ValueError) as exc:
        parser.error(f"the board does not assemble: {exc}")
    url = database_url(config.database_url, base)
    shown = make_url(url).render_as_string(hide_password=True)
    if args.check:
        done = settled(url)
        print(json.dumps({"store": shown, "settled": done}))
        return 0 if done else 1
    maintain(
        url,
        machines,
        base=base,
        state_dir=config.scheduler.state_dir,
        keys=board.keys,
        board_name=config.bridge.board,
        fold=True,
        inbox_files=config.github.inbox_files if config.github else None,
    )
    print(json.dumps({"store": shown}))
    return 0


def settled(url: str) -> bool:
    """Whether `maintain` has nothing to change: the store is at the chain's head and the stored snapshot holds the stamp
    of its table definition. It writes nothing, and reads no stamp of a store behind the head, which may hold none of
    the tables."""
    engine = store_engine(url)
    try:
        return at_head(engine) and snapshots_built(engine)
    finally:
        engine.dispose()


def maintain(
    url: str,
    machines: Mapping[str, dict],
    *,
    base: Path | None = None,
    state_dir: str | None = None,
    keys: TaskKeys | None = None,
    board_name: str | None = None,
    fold: bool = False,
    inbox_files: str | None = None,
) -> None:
    """The work `HistoryStore` used to do on every open: the schema.

    With `board_name` (the config's `[bridge] board`) a Task stream with no UUID takes the v5 of it and its key; a store holding one is refused without it.

    With `inbox_files` (a glob for the old GitHub inbox databases) it copies their rows into the store once and leaves the files.

    With a `base` (the config's directory) it also imports the operator files found there, and in `state_dir` under it.
    With `fold` (the `starpulse migrate` run) it folds the Task History and the `machine:events` the store holds past
    the read model's checkpoints, placing machine tasks with `keys`. It never rebuilds a row: a table's shape changes by
    a migration, and `starpulse replay` repairs a named Task. The stored snapshot is emptied only when its own table
    definition changed.
    """
    engine = store_engine(url)
    try:
        migrate(engine, board_name)
        log = EventLog(url, engine=engine)  # opened after the migration: an unmigrated store refuses its events
        if fold:
            projector = Projector(engine, EventStore(engine), log=log, drawn=machines, keys=keys)
            projector.catch_up()
            build_snapshots(engine)
        if base is not None:
            import_files(log, base, base / (state_dir or ""))
        if inbox_files is not None:
            _carry_inbox(log, inbox_files)
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


def _carry_inbox(log: EventLog, pattern: str) -> None:

    if log.setting(INBOX_CARRIED) is not None:
        return
    files = sorted(glob.glob(pattern))
    for file in files:
        logger.info("migrate: carried the GitHub inbox from %s: %s", file, carry_over(log.engine, Path(file)))
    if files:
        log.set_setting(INBOX_CARRIED, pattern)


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
