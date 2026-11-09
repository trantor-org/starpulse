"""`starpulse migrate-proposals [--reverse]`: give a native board's Proposed tasks their own `PROP-N` ids, or give them
their task numbers back.

The config's `[board]` names the board (`path`, `proposal_prefix`, `task_file_name`, the machine whose proposed state
the migration reads). Every old id stays an alias of the new one, so a link to it still resolves, and the map of old id
to new id is written to `--map` (default `<board>/proposal-aliases.json`); `--reverse` reads that map to restore the
ids. A rerun finishes what an interrupted one began. Stop `serve` first: it must not write a task while its file is
renamed, and it reads the renamed files when it starts.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from starpulse.board.adapters.native import DEFAULT_PATH, board
from starpulse.board.adapters.proposal_migration import migrate, reverse
from starpulse.runtime.config import ConfigError, discover, load

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Migrate (or, with `--reverse`, restore) the board's proposals; 0 when done, 1 when it cannot run."""
    parser = argparse.ArgumentParser(
        prog="starpulse migrate-proposals", description="move the Proposed tasks to PROP-N ids, or back"
    )
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    parser.add_argument("--map", type=Path, help="the old-to-new id map (default <board>/proposal-aliases.json)")
    parser.add_argument("--reverse", action="store_true", help="restore each task number the map records")
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    base = path.parent if path else Path.cwd()
    settings = dict(config.board)
    prefix = str(settings.get("proposal_prefix", ""))
    if not prefix:
        print("starpulse migrate-proposals: the [board] sets no proposal_prefix", file=sys.stderr)
        return 1
    try:
        built = board(settings, base)
    except (OSError, ValueError) as exc:
        parser.error(f"the board does not assemble: {exc}")
    root = base / str(settings.get("path", DEFAULT_PATH))
    alias_map = args.map or root / "proposal-aliases.json"
    file_name = str(settings.get("task_file_name", "title"))
    moved = (
        reverse(root, alias_map, file_name)
        if args.reverse
        else migrate(root, prefix, built.roles.proposed, alias_map, file_name)
    )
    print(json.dumps({"map": str(alias_map), "reverse": args.reverse, "moved": len(moved)}))
    return 0
