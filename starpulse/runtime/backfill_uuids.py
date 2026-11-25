"""`starpulse backfill-uuids`: give every board file and every Task in History the UUID v5 of its board and key.

    starpulse backfill-uuids --config starpulse.toml [--root COPY] [--files-only | --history-only]

It writes `uuid:` under the `id:` line of each board file that has none and appends one `FieldsEdited` carrying the same
UUID to each Task stream of History that has none, then prints one JSON line: `changed` (files written), `skipped` (the
paths of files with no front matter or `id`), `history` (Tasks stamped) and `stamped` (their keys). A second run changes
nothing. `--root` stamps another copy of the board folder, and `--files-only` leaves History alone, so a copy of the
board takes the run without the live store. `--history-only` leaves every file alone and stamps History with the v5 of
each key. Stop `serve` first for a run that writes files; a History-only run needs no stop, since a stream that
`serve` appends to meanwhile is read again and stamped on the retry.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from starpulse.board.adapters import item_uuid
from starpulse.board.adapters.native import DEFAULT_PATH
from starpulse.event_log.store import EventStore
from starpulse.runtime.assembly import declared, history_store
from starpulse.runtime.config import ConfigError, discover, load

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="starpulse backfill-uuids", description="give every board item the UUID v5 of its board and key"
    )
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    parser.add_argument(
        "--root",
        type=Path,
        help="the board folder to stamp (default the config's board folder); without --files-only History still takes the UUIDs, so pass both for a copy",
    )
    parser.add_argument(
        "--files-only",
        action="store_true",
        help="stamp the files and leave History as it is, so a copy of the board takes the run; stop `serve` before a run on the live board",
    )
    parser.add_argument(
        "--history-only",
        action="store_true",
        help="stamp History with each Task's UUID v5 and leave every board file as it is; `serve` may keep running",
    )
    args = parser.parse_args(argv)
    if args.files_only and args.history_only:
        parser.error("--files-only and --history-only exclude each other")
    path = discover(args.config)
    try:
        config = load(path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    base = path.parent if path else Path.cwd()
    if config.board_type != "native":
        parser.error(
            f"{path or 'starpulse.toml'}: the board type is {config.board_type!r}; backfill-uuids stamps a native board, so point --config at one"
        )
    root = args.root or base / str(config.board.get("path", DEFAULT_PATH))
    stamped = item_uuid.Stamped() if args.history_only else item_uuid.stamp_files(root, config.bridge.board)
    history: list[str] = []
    if not args.files_only:
        _, machines, *_ = declared(config, base)
        history = item_uuid.stamp_history(
            EventStore(history_store(config, base, machines).engine), config.bridge.board, stamped.tasks
        )
    print(
        json.dumps(
            {"changed": len(stamped.changed), "skipped": [str(p) for p in stamped.skipped], "history": len(history), "stamped": history}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
