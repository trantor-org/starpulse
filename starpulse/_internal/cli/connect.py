"""`starpulse connect native|backlog|jira`: check that a tracker answers, then write the `[board]` table for it.

    starpulse connect native --path .starpulse/board --machine board.yaml
    starpulse connect backlog --path backlog
    JIRA_TOKEN=... starpulse connect jira --url https://acme.atlassian.net --project PAY --workflow "Payments Software Workflow"

Each reads the tracker the way the server would (a Backlog.md or native board's task files, or a Jira site's workflow
and project issues), and only then replaces the `[board]` table of the config (`--config`, default `starpulse.toml`)
with the adapter's settings, keeping every other table and comment. It prints one line saying what it read and exits
0; a tracker that does not answer, or a config it cannot rewrite, writes nothing, says why on stderr and exits 1.
A Jira token is never an argument and never written: the config names the variable (`JIRA_TOKEN`) that holds it.
Connecting `native` creates its board directory, empty, when it is absent, as serving does.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import tomllib

from starpulse._internal.adapters.boards import jira, native, upstream_backlog
from starpulse.contracts.adapters import BoardTask
from starpulse._internal.settings.config import ConfigError, load

__all__ = ["main"]

DEFAULT_CONFIG = Path("starpulse.toml")
#: The variable a Jira token is read from, and the one the written config names.
TOKEN_ENV = "JIRA_TOKEN"
_BOARD_HEADER = re.compile(r"\[board\][ \t]*(?:#.*)?\r?\n?")


class ConnectError(Exception):
    """A tracker that does not answer or a config that cannot be rewritten; the message is why."""


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def _read_files(root: Path) -> str:
    """What a scan of the Markdown board in `root` finds: its task and lane counts."""
    tasks: list[BoardTask] = []
    upstream_backlog.UpstreamBacklog(root, tasks.append).scan()
    lanes = len(upstream_backlog.read_config(root).statuses)
    return f"Read {_count(len(tasks), 'task')} in {_count(lanes, 'lane')}"


def _board_files(settings: dict[str, Any], base: Path, *, create: bool) -> str:
    """Check the Markdown board `settings` names, as the server builds it, and say what it holds."""
    path = str(settings["path"])
    root = base / path
    try:
        if create:
            native.board(settings, base)
        else:
            if not root.is_dir():
                raise ValueError(f"{root} is not a directory")
            upstream_backlog.board(settings, base)
        found = _read_files(root)
    except (OSError, ValueError) as error:
        raise ConnectError(str(error)) from error
    return f"{found} from {path.rstrip('/')}/"


def _jira(settings: dict[str, Any]) -> str:
    """Import the workflow and read the project's issues, as the server does; say how many of each."""
    try:
        project, _ = jira.open_project(settings)
        tasks: list[BoardTask] = []
        project.scan(tasks.append, lambda task: None)
    except (OSError, ValueError, KeyError) as error:
        raise ConnectError(str(error)) from error
    states = _count(len(project.machine["states"]), "state")
    return f"Imported {settings['workflow']} ({states}) · read {_count(len(tasks), 'issue')} from {settings['project']}"


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
    backlog = tracker("backlog", "a Backlog.md project's task files")
    backlog.add_argument("--path", default="backlog", help="the project's backlog/ directory (default backlog)")
    backlog.add_argument(
        "--machine", help="a machine file for the Board, which decides the moves offered (relative to the config)"
    )
    backlog.add_argument("--command", help="the backlog CLI that writes moves (default backlog)")
    site = tracker("jira", f"a Jira project, read-only; the API token is read from ${TOKEN_ENV}")
    site.add_argument("--url", required=True, help="the Jira site (https://acme.atlassian.net)")
    site.add_argument("--project", required=True, help="the Jira project key, which is each task's team (PAY)")
    site.add_argument("--workflow", required=True, help="the Jira workflow imported as the Board machine")
    site.add_argument("--user", help=f"Jira Cloud: the account the API token in ${TOKEN_ENV} belongs to")
    return parser


def _settings(args: argparse.Namespace) -> dict[str, Any]:
    """The `[board]` settings `args` names, only those it gave."""
    if args.tracker == "jira":
        given = {"type": "jira", "url": args.url, "project": args.project, "workflow": args.workflow}
        return {**given, "token_env": TOKEN_ENV, **({"user": args.user} if args.user else {})}
    kind = {"native": "native", "backlog": "upstream_backlog"}[args.tracker]
    optional = {"machine": args.machine, "command": getattr(args, "command", None)}
    return {"type": kind, "path": args.path, **{key: value for key, value in optional.items() if value}}


def main(argv: Sequence[str] | None = None) -> int:
    """Check the tracker, write the config and print one line; 1 with the reason on stderr when either cannot be done."""
    args = _parser().parse_args(argv)
    settings = _settings(args)
    try:
        if args.tracker == "jira":
            found = _jira(settings)
        else:
            found = _board_files(settings, args.config.parent, create=args.tracker == "native")
        _write(args.config, settings)
    except ConnectError as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1
    print(f"✓ {found} · wrote [board] to {args.config}")
    return 0
