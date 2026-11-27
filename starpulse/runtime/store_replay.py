"""`starpulse replay --config FILE --task ID | --first N --last M`: fold named Tasks' rows again from their History.

The one repair an operator runs when a Task's row is wrong. No start, deploy, reload or machine activation does it:
a table's shape changes by a migration. It replaces the rows of the Tasks named, or of those with an Event at a position
in `--first` to `--last`, in one write transaction, and touches no other Task, no machine row and no checkpoint. A
running Board writer repaints a replaced row at the Task's next Event or its restart. It prints one JSON line:
`replayed`, the Tasks replaced. The exit code is 2 for a config that cannot be read or a call naming no Task.
"""

import argparse
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

lazy from starpulse.event_log.event_log import EventLog, store_engine
lazy from starpulse.event_log.opening import database_url
lazy from starpulse.event_log.readmodel.projector import BATCH, Projector
lazy from starpulse.event_log.store import EventStore
lazy from starpulse.runtime.assembly import declared
lazy from starpulse.runtime.config import ConfigError, discover, load

__all__ = ["main", "replay"]


def main(argv: Sequence[str] | None = None) -> int:
    """Replay the Tasks the call names in the store the config names; 0 once they are replaced."""
    parser = argparse.ArgumentParser(prog="starpulse replay", description="fold named Tasks' rows again from their History")
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    parser.add_argument("--task", action="append", default=[], help="replay this Task; repeatable")
    parser.add_argument("--first", type=int, help="replay the Tasks with an Event at or after this position")
    parser.add_argument("--last", type=int, help="replay the Tasks with an Event at or before this position")
    args = parser.parse_args(argv)
    if not (args.task or args.first is not None or args.last is not None):
        parser.error("name a Task with --task, or a range with --first and --last")

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
    tasks = replay(database_url(config.database_url, base), machines, tasks=args.task, first=args.first, last=args.last)
    print(json.dumps({"replayed": tasks}))
    return 0


def replay(
    url: str,
    machines: Mapping[str, dict],
    *,
    tasks: Sequence[str] = (),
    first: int | None = None,
    last: int | None = None,
) -> list[str]:
    """Replace the row of each Task in `tasks`, and of each with an Event at a position from `first` to `last`, with one
    folded from its whole History; the Tasks replaced."""
    engine = store_engine(url)
    try:
        store = EventStore(engine)
        named = {*tasks, *_ranged(store, first, last)}
        return Projector(engine, store, log=EventLog(url, engine=engine), drawn=machines).rebuild(named)
    finally:
        engine.dispose()


def _ranged(store: EventStore, first: int | None, last: int | None) -> set[str]:
    """The Tasks with an Event at a position in `first` to `last`, either end open."""
    if first is None and last is None:
        return set()
    found: set[str] = set()
    position = max((first or 1) - 1, 0)
    while batch := store.read_after("task", position, BATCH):
        for event in batch:
            if last is not None and event.position > last:
                return found
            found.add(event.subject_id)
        position = batch[-1].position
    return found
