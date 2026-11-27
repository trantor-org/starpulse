"""`starpulse parity --config FILE [--import]`: whether every task of the board has a History that replays to its file.

It reads the open, completed and archived task files the config's board holds and the retired tasks of the store the
config names, and prints one JSON line: the tasks `checked`, those `missing` a History, those `differing` (each with its
differing lines) and, with `--import`, the tasks `imported` first, each given one `TaskImported` Event, and the tasks `backfilled`, each given the creation
answers (ADR needed, duplicate search and resolution) its file holds and its History lacks. The store is
read, and written only by `--import`. With `--remove`, a report listing no task `missing` a History removes every file
the open, completed and archived task folders hold (`removed` counts them: a task is read from its History alone), and a
`differing` task no longer fails the run. The exit code is 0 for an empty report, 1 for a report that lists a task, and 2
for a flag the command does not allow or a config that cannot be read."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

lazy from sqlalchemy import create_engine

lazy from starpulse.board.adapters.task_parity import backfill_answers, check, filed, import_missing, unfile
lazy from starpulse.event_log.checkpoints import Checkpoints
lazy from starpulse.event_log.opening import database_url
lazy from starpulse.event_log.store import EventStore
lazy from starpulse.runtime.config import ConfigError, discover, load

REMOVED = "parity:removed"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starpulse parity", description="compare every task's History with its file")
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    parser.add_argument("--import", dest="load", action="store_true", help="first import each task without History")
    parser.add_argument(
        "--remove", action="store_true", help="then remove the task files, if no task is missing a History"
    )
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    base = path.parent if path else Path.cwd()
    engine = create_engine(database_url(config.database_url, base))
    root = base / str(config.board.get("path", "backlog"))
    checkpoints = Checkpoints(engine)
    try:
        if args.remove and checkpoints.load(REMOVED)[0] is not None:
            print(json.dumps({"skipped": "already ran"}))
            return 0
        imported = import_missing(filed(root, engine), engine) if args.load else []
        backfilled = backfill_answers(filed(root, engine), engine) if args.load else []
        report = check(filed(root, engine), EventStore(engine))
        removed = 0
        if args.remove and not report.missing:
            removed = unfile(root)
            checkpoints.save(REMOVED, 1)
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
                "checked": report.checked,
                **({"imported": imported, "backfilled": backfilled} if args.load else {}),
                "missing": report.missing,
                "differing": report.differing,
                **({"removed": removed} if args.remove else {}),
            }
        )
    )
    return 0 if (not report.missing if args.remove else report.clean) else 1
