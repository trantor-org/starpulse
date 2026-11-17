"""`starpulse connect native`: check that the board answers, then write the `[board]` table for it.

    starpulse connect native --path .starpulse/board --machine board.yaml

It reads the native board's task files the way the server would, and only then replaces the `[board]` table of the
config (`--config`, default `starpulse.toml`) with the adapter's settings, keeping every other table and comment. It
prints one line saying what it read and exits 0; a board that does not answer, or a config it cannot rewrite, writes
nothing, says why on stderr and exits 1. Connecting `native` creates its board directory, empty, when it is absent, as
serving does.
"""

import argparse
import json
import os
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from starpulse.board.adapters import native, native_scan
from starpulse.contracts.adapters import BoardTask
from starpulse.runtime.config import ConfigError, load

__all__ = ["main"]

DEFAULT_CONFIG = Path("starpulse.toml")
_BOARD_HEADER = re.compile(r"\[board\][ \t]*(?:#.*)?\r?\n?")


class ConnectError(Exception):
    """A tracker that does not answer or a config that cannot be rewritten; the message is why."""


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def _read_files(root: Path) -> str:
    """What a scan of the Markdown board in `root` finds: its task and lane counts."""
    tasks: list[BoardTask] = []
    native_scan.NativeScan(root, tasks.append).scan()
    lanes = len(native_scan.read_config(root).statuses)
    return f"Read {_count(len(tasks), 'task')} in {_count(lanes, 'lane')}"


def _board_files(settings: dict[str, Any], base: Path) -> str:
    """Check the native board `settings` names, as the server builds it, and say what it holds."""
    path = str(settings["path"])
    try:
        native.board(settings, base)
        found = _read_files(base / path)
    except (OSError, ValueError) as error:
        raise ConnectError(str(error)) from error
    return f"{found} from {path.rstrip('/')}/"


def _board_table(text: str, settings: Mapping[str, Any]) -> str:
    """`text` with its `[board]` table replaced by `settings`, or the table appended when it has none."""
    table = "[board]\n" + "".join(
        f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in settings.items()
    )
    lines = text.splitlines(keepends=True)
    start = next((at for at, line in enumerate(lines) if _BOARD_HEADER.fullmatch(line)), None)
    if start is None:
        head = text if not text or text.endswith("\n") else f"{text}\n"
        return f"{head}\n{table}" if head else table
    end = next((at for at in range(start + 1, len(lines)) if lines[at].lstrip().startswith("[")), len(lines))
    while end - 1 > start and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1  # blank lines and comments just above the next table belong to it
    return "".join(lines[:start]) + table + "".join(lines[end:])


def _write(path: Path, settings: Mapping[str, Any]) -> None:
    """Write `settings` as the config's `[board]`, only when the result still loads as a StarPulse config."""
    try:
        text = path.read_text() if path.exists() else ""
        tomllib.loads(text)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConnectError(f"{path}: {error}") from error
    new = _board_table(text, settings)
    try:
        if tomllib.loads(new).get("board") != dict(settings):
            raise ConnectError(f"{path}: cannot replace its board setting with a [board] table; edit it by hand")
    except tomllib.TOMLDecodeError as error:
        raise ConnectError(f"{path}: cannot write a [board] table beside its board setting: {error}") from error
    scratch = path.with_name(f"{path.name}.tmp")  # not the config, so a server reading it never sees half of one
    try:
        scratch.write_text(new)
        try:
            load(scratch)
        except (ConfigError, OSError, ValueError) as error:
            raise ConnectError(f"{path}: the new [board] makes the config fail: {error}") from error
        os.replace(scratch, path)
    finally:
        scratch.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="starpulse connect",
        description="check that a tracker answers, then write the [board] table of the config for it",
    )
    trackers = parser.add_subparsers(dest="tracker", required=True, metavar="tracker")

    def tracker(name: str, summary: str) -> argparse.ArgumentParser:
        sub = trackers.add_parser(name, description=summary, help=summary, allow_abbrev=False)
        sub.add_argument(
            "--config", type=Path, default=DEFAULT_CONFIG, help=f"the TOML config to write (default {DEFAULT_CONFIG})"
        )
        return sub

    own = tracker("native", "StarPulse's own Markdown board, created empty when it is absent")
    own.add_argument(
        "--path", default=native.DEFAULT_PATH, help=f"the board's directory (default {native.DEFAULT_PATH})"
    )
    own.add_argument(
        "--machine", help="a machine file for the Board, which decides the moves offered (relative to the config)"
    )
    return parser


def _settings(args: argparse.Namespace) -> dict[str, Any]:
    """The `[board]` settings `args` names, only those it gave."""
    return {"type": "native", "path": args.path, **({"machine": args.machine} if args.machine else {})}


def main(argv: Sequence[str] | None = None) -> int:
    """Check the tracker, write the config and print one line; 1 with the reason on stderr when either cannot be done."""
    args = _parser().parse_args(argv)
    settings = _settings(args)
    try:
        found = _board_files(settings, args.config.parent)
        _write(args.config, settings)
    except ConnectError as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1
    print(f"✓ {found} · wrote [board] to {args.config}")
    return 0
