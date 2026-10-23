"""`starpulse import-board`: import the board and its recorded runs as Events, then verify every Task by replay.

    starpulse import-board --config starpulse.toml

Each Task the store's lane history names becomes `TaskImported` of the board's record, its lane changes imported
`Transitioned` Events; each recorded run entry becomes an Event of its run's stream (`starpulse._internal.board.board_import`).
It prints one JSON line, the verification report: `tasks`, `imported`, `equal`, `differing` (task to the fields whose
replay differs), `gaps` (tasks whose lane history ends elsewhere than the board does, imported as the board shows them),
`runs`, `runs_imported` and `verified`. The exit code is 0 when every Task replays to its record, 1 when one does not,
and 2 for a config that cannot be read or a board that does not assemble. A second run imports nothing and verifies again.
`--dry-run` imports into a scratch store and leaves the real one untouched. Stop `serve` first for a real run.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select

from starpulse._internal.board.board_import import import_board
from starpulse._internal.config.config import ConfigError, discover, load
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.tables import events
from starpulse._internal.runs.run_events import STREAM
from starpulse._internal.runs.run_streams import RunStreams
from starpulse._internal.server.assembly import assemble, history_store
from starpulse._internal.store import EventStore

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Import and verify; 0 when every Task replays to its record, 1 otherwise."""
    parser = argparse.ArgumentParser(
        prog="starpulse import-board", description="import the board and its recorded runs, verified by replay"
    )
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    parser.add_argument(
        "--dry-run", action="store_true", help="import into a scratch store and report, leaving the real one as it is"
    )
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    base = path.parent if path else Path.cwd()
    try:
        board, feed = assemble(config, base, None, [])
    except (OSError, ValueError) as exc:
        parser.error(f"the board does not assemble: {exc}")
    if board.read is None:
        parser.error("the board keeps no task records")
    history = history_store(config, base, feed.machines)
    lanes = history.lane_changes()
    records = {task: record for task in dict.fromkeys(lane[1] for lane in lanes) if (record := board.read(task))}
    with history.engine.connect() as db:
        rows = db.execute(
            select(events.c.event_id, events.c.fields).where(events.c.stream == STREAM).order_by(events.c.id)
        )
        runs = [(event_id, dict(fields)) for event_id, fields in rows]
    if args.dry_run:
        with tempfile.TemporaryDirectory() as scratch:
            store = EventStore(EventLog(f"sqlite:///{Path(scratch) / 'events.sqlite'}").engine)
            report = import_board(store, records, lanes, runs, RunStreams(store).record)
    else:
        live = EventStore(history.engine)
        report = import_board(live, records, lanes, runs, RunStreams(live).record)
    print(json.dumps({**dataclasses.asdict(report), "verified": report.ok}))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
