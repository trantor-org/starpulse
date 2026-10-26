"""`starpulse backup --to <dir> [--keep N]`: a verified, vacuumed copy of the history store, written into `--to`.

`VACUUM INTO` writes the copy under a read lock held only for the copy, so the WAL-mode store keeps serving. The copy
is proven with `PRAGMA integrity_check` before it counts, and only the newest `--keep` copies stay in the directory.
A store that is not SQLite exits 2: its own backup tool owns that. The summary is one JSON line on stdout.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

from starpulse.runtime.config import discover, load
from starpulse.event_log.opening import database_url

PREFIX = "starpulse-"
SUFFIX = ".db"
BUSY_TIMEOUT_S = 30


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def snapshot(db: Path, out: Path) -> None:
    """Write a verified copy of `db` at `out`, or raise leaving nothing at `out`."""
    partial = out.with_name(f".{out.name}.partial")
    partial.unlink(missing_ok=True)  # VACUUM INTO refuses to overwrite
    try:
        source = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=BUSY_TIMEOUT_S)
        try:
            source.execute("VACUUM INTO ?", (str(partial),))
        finally:
            source.close()
        # A corrupt file that exists reads as success; prove the copy before it counts.
        with closing(sqlite3.connect(partial)) as check:
            verdict = check.execute("PRAGMA integrity_check").fetchone()[0]
        if verdict != "ok":
            raise sqlite3.DatabaseError(f"integrity_check failed on the copy: {verdict}")
        partial.replace(out)
    finally:
        partial.unlink(missing_ok=True)


def prune(dest: Path, keep: int) -> None:
    """Delete all but the newest `keep` copies. The names sort by the time they were taken."""
    for old in sorted(dest.glob(f"{PREFIX}*{SUFFIX}"))[:-keep]:
        old.unlink()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="starpulse backup", description=__doc__)
    p.add_argument("--to", type=Path, required=True, help="directory the copies are written to")
    p.add_argument("--keep", type=positive_int, default=14, help="copies kept in --to, the newest (default 14)")
    p.add_argument("--config", type=Path, help="the starpulse.toml that names the store, as `serve` reads it")
    args = p.parse_args(argv)

    try:
        path = discover(args.config)
        url = database_url(load(path).database_url, path.parent if path else Path.cwd())
    except (OSError, ValueError) as exc:
        print(f"backup: config unreadable: {exc}", file=sys.stderr)
        return 1
    if not url.startswith("sqlite:///"):
        print("backup: the store is not SQLite; use your database's own backup", file=sys.stderr)
        return 2

    args.to.mkdir(parents=True, exist_ok=True)
    out = args.to / f"{PREFIX}{time.strftime('%Y%m%dT%H%M%S')}{SUFFIX}"
    try:
        snapshot(Path(url.removeprefix("sqlite:///")), out)
    except (OSError, sqlite3.Error) as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    prune(args.to, args.keep)
    kept = len(list(args.to.glob(f"{PREFIX}*{SUFFIX}")))
    print(json.dumps({"copy": str(out), "integrity": "ok", "kept": kept}))
    return 0
