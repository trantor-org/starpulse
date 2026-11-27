"""`starpulse doc-index`: index the board's doc files, and list where the files and the index disagree.

    starpulse doc-index --config starpulse.toml [--check]

Without `--check` it gives every doc file with no row its row, then reports as `--check` does. It prints one JSON line:
`indexed` (rows added now), `unindexed` (doc files with no row) and `missing` (rows with no file), as paths under the
board. The exit code is 0 when the files and the rows agree, 1 when they do not, and 2 for a config that cannot be read
or a board that does not assemble. `serve` imports at start, so an unindexed file shows only until the next start.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from starpulse.board.adapters import native_doc_import
from starpulse.board.adapters.native import DEFAULT_PATH
from starpulse.board.adapters.native_doc_index import DocIndex
from starpulse.runtime.assembly import declared, history_store
from starpulse.runtime.config import ConfigError, discover, load

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Import unless `--check`, then report the disagreement; 0 when there is none."""
    parser = argparse.ArgumentParser(prog="starpulse doc-index", description="index the doc files with no row, then list the files and rows that disagree")
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    parser.add_argument("--check", action="store_true", help="write nothing: only list the files and rows that disagree")
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    base = path.parent if path else Path.cwd()
    try:
        _, machines, *_ = declared(config, base)
    except (OSError, ValueError) as exc:
        parser.error(f"the board does not assemble: {exc}")
    root = base / str(config.board.get("path", DEFAULT_PATH))
    index = DocIndex(root, history_store(config, base, machines).engine)
    indexed = 0 if args.check else native_doc_import.import_files(root, index)
    unindexed, missing = native_doc_import.check(root, index)
    print(json.dumps({"indexed": indexed, "unindexed": unindexed, "missing": missing}))
    return 1 if unindexed or missing else 0


if __name__ == "__main__":
    sys.exit(main())
