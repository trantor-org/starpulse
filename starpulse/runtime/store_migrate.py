"""`starpulse migrate --config FILE`: bring the store the config names to its schema, its one-time imports and summaries.

Opening a store runs none of this (`HistoryStore` refuses one the chain has not reached), so a new or upgraded store is
migrated here before `serve` opens it. Besides the schema and the summaries it moves the operator state once kept in
files (the scheduler switch, the history window, the run ledger) into the store, each once: the file is logged as
imported and renamed with `RETIRED_SUFFIX`, so a second run finds the schema at the chain's head and nothing to import.
With `[board] source_labels` set it also appends, to each task's History, the move of its one label matching that regex to
its `source` (`label_sources`, which first imports a task without History), and a second run finds nothing left to move.
Each task's History is archived exactly when its file sits in `completed/` or `archive/tasks/` (`settle_archived`), the file winning.
With `[board] files_win` set it also appends, to each task's History that replays differently from its file, the Events that bring it to the file (`files_win`), and a second run finds nothing left to bring. The steps share one parse of the task files and one replay of each History, so the run reads each once, not once per step. A run ends by storing, under `PARITY_LEDGER`, each task file's and retired row's digest and its History version; the next run parses and replays only the tasks whose digest or version moved or that the ledger lacks (and all of them when a step's source or the `files_win` switch changed), so a run with nothing to change reads no History. The comment reconcile (`comment_parity`) runs once, on the migrate of the live store, and not under a rehearsal's copy. It prints one JSON line: `store` (the database URL, password hidden). The exit code is 2 for a flag the command does
not allow, a config that cannot be read, or a board the config does not assemble.
"""

import argparse
import glob
import hashlib
import inspect
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from starpulse.contracts.adapters import TaskKeys
    from starpulse.event_log.event_log import EventLog

__all__ = ["RETIRED_SUFFIX", "main", "maintain"]

logger = logging.getLogger(__name__)

#: What an imported file is renamed to, so the value it held can still be read by hand.
RETIRED_SUFFIX = ".imported"
#: The setting that records the old inbox file carried into the store, so a second run copies nothing.
INBOX_CARRIED = "github_inbox_carried"
#: The setting holding, for each task the parity steps checked, the digest of its file and its History version then.
PARITY_LEDGER = "migrate_parity_ledger"


def main(argv: Sequence[str] | None = None) -> int:
    """Migrate the store the config names, import its old files and build its summaries; 0 once it is at the head."""
    parser = argparse.ArgumentParser(prog="starpulse migrate", description="bring the store to its current schema")
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    args = parser.parse_args(argv)
    # The store, the board and the config cost over a second to import: `--help` and a flag error pay none of it.
    from sqlalchemy.engine import make_url  # noqa: PLC0415 - import cost, paid only by a run that migrates

    from starpulse.event_log.opening import database_url  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.runtime.assembly import declared  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.runtime.config import ConfigError, discover, load  # noqa: PLC0415 - import cost, paid only by a run that migrates

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
    maintain(
        url,
        machines,
        base=base,
        state_dir=config.scheduler.state_dir,
        keys=board.keys,
        fold=True,
        inbox_files=config.github.inbox_files if config.github else None,
    )
    from starpulse.board.adapters.comment_parity import reconcile_comments  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.board.adapters.files_win import bring_to_files  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.board.adapters.label_sources import move_key_labels  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.board.adapters.meta_backfill import backfill_meta  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.board.adapters.settle_archived import settle_archived  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.board.adapters.task_history import TaskHistory  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.board.adapters.native import _record_of  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.board.adapters.task_parity import Replays, align_claims, pending  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.board.model.markdown import render  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.event_log.readmodel.fold import replay  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.event_log.event_log import EventLog, store_engine  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.runtime.config import rehearsing  # noqa: PLC0415 - import cost, paid only by a run that migrates

    root = base / str(config.board.get("path", "backlog"))
    engine = store_engine(url)
    try:
        # A task whose file and History version match the last run's ledger is skipped; the rest are parsed and replayed once for all the steps, and a step that writes drops what it wrote to.
        log = EventLog(url, engine=engine)
        stamp = _stamp(files_win=bool(config.board.get("files_win")), steps=(settle_archived, align_claims, backfill_meta, bring_to_files, reconcile_comments, TaskHistory, replay, render, _record_of))
        kept = log.setting(PARITY_LEDGER) or {}
        checked = pending(root, engine, kept.get("tasks", {}) if kept.get("stamp") == stamp else {})
        due, rows = checked, Replays(engine)
        settle_archived(root, engine, due.files, rows)
        if (pattern := config.board.get("source_labels")) and move_key_labels(root, str(pattern), engine):
            rows.drop()
        align_claims(due.items, engine, rows)
        backfill_meta(root, engine, due.items, rows)
        if reconcile_comments(root, engine, rehearsing=rehearsing()):  # it rewrites files and appends to Histories
            due = pending(root, engine, {})
            rows.drop()
        if config.board.get("files_win"):
            brought = bring_to_files(due.items, engine, rows)
            logger.info("migrate: brought %d task Histories to their files", brought)
        log.set_setting(PARITY_LEDGER, {"stamp": stamp, "tasks": checked.ledger})  # what a step or the reconcile wrote moved its task's version, so that task is checked once more
    finally:
        engine.dispose()
    print(json.dumps({"store": make_url(url).render_as_string(hide_password=True)}))
    return 0


def _stamp(*, files_win: bool, steps: Sequence[Any]) -> str:
    """The digest of what the parity steps would do: the source of their modules and the config switch, so a changed step checks every task again."""
    sources = {inspect.getsourcefile(step) for step in steps}
    code = b"".join(Path(file).read_bytes() for file in sorted(sources) if file)
    return hashlib.sha256(code + bytes([files_win])).hexdigest()


def maintain(
    url: str,
    machines: Mapping[str, dict],
    *,
    base: Path | None = None,
    state_dir: str | None = None,
    keys: TaskKeys | None = None,
    fold: bool = False,
    inbox_files: str | None = None,
) -> None:
    """The work `HistoryStore` used to do on every open: the schema.

    With `inbox_files` (a glob for the old GitHub inbox databases) it copies their rows into the store once and leaves the files.

    With a `base` (the config's directory) it also imports the operator files found there, and in `state_dir` under it.
    With `fold` (the `starpulse migrate` run, the only writer besides the Board child) it folds the Task History and the
    `machine:events` the store holds into the read model, placing machine tasks with `keys`; the read model and the
    stored snapshot, and the summaries, are rebuilt first when their stamp differs.
    """
    from starpulse.event_log.event_log import EventLog, store_engine  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.event_log.migrate import migrate  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.event_log.readmodel.projector import Projector  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.event_log.readmodel.snapshot_store import build as build_snapshots  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.event_log.store import EventStore  # noqa: PLC0415 - import cost, paid only by a run that migrates

    engine = store_engine(url)
    try:
        migrate(engine)
        log = EventLog(url, engine=engine)  # opened after the migration: an unmigrated store refuses its events
        if fold:
            projector = Projector(engine, EventStore(engine), log=log, drawn=machines, keys=keys)
            projector.build()
            build_snapshots(engine, projector.stamp())
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
    from starpulse.board.adapters import history_window  # noqa: PLC0415 - import cost, paid only by a run that migrates
    from starpulse.scheduler.model import ledger, toggle  # noqa: PLC0415 - import cost, paid only by a run that migrates

    _import_setting(log, toggle.KEY, state_dir / toggle.TOGGLE_FILE, "enabled")
    _import_setting(log, history_window.KEY, base / history_window.SETTINGS_FILE, "history_hours")
    _import_runs(log.engine, state_dir / ledger.LEDGER_FILE)


def _carry_inbox(log: EventLog, pattern: str) -> None:
    from starpulse.github.adapters.outbound.carry_over import carry_over  # noqa: PLC0415 - import cost, paid only by a run that migrates

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
    from sqlalchemy import insert, select  # noqa: PLC0415 - import cost, paid only by a run that migrates

    from starpulse.event_log.tables import scheduler_runs  # noqa: PLC0415 - import cost, paid only by a run that migrates

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
