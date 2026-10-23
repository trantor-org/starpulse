"""`starpulse command run`: the argv a project's `[project.commands]` maps a step name to, run with no shell."""

from __future__ import annotations

import argparse
import subprocess
import time
from collections.abc import Mapping
from typing import Any

from starpulse._internal.cli.agent_wire import CliError
from starpulse._internal.config.config import ConfigError, discover, load

#: What a caller does for a step the project has not mapped.
FALLBACK = "AGENTS.md"


class _Values(dict[str, str]):
    """The placeholders' values; `{worktree}` is the git toplevel, looked up only when an argv uses it."""

    def __missing__(self, key: str) -> str:
        if key != "worktree":
            raise CliError(
                "usage",
                f"{{{key}}} has no value; pass it as --arg {key}=VALUE" + (" or --task" if key == "task" else ""),
            )
        done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
        if done.returncode:
            raise CliError("usage", "{worktree} needs a git checkout; this directory is in none")
        return self.setdefault(key, done.stdout.strip())


def _argv(template: tuple[str, ...], values: _Values, extra: list[str]) -> list[str]:
    argv: list[str] = []
    for element in template:
        argv.extend(extra if element == "{args}" else [element.format_map(values)])
    return argv


def run(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Run one named command; the child's output streams to stderr and the document is its name, argv, exit and seconds."""
    path = discover(args.config)
    try:
        commands = load(path).project.commands
    except (ConfigError, OSError, ValueError) as exc:
        raise CliError("refused", f"config: {exc}") from exc
    if args.name not in commands:
        raise CliError(
            "not_found", f"no [project.commands] entry {args.name}; do the step as {FALLBACK} says", fallback=FALLBACK
        )
    values = _Values()
    if args.task is not None:
        values["task"] = args.task
    for pair in args.arg:
        name, sep, value = pair.partition("=")
        if not sep:
            raise CliError("usage", f"--arg {pair!r} is not NAME=VALUE")
        values[name] = value
    argv = _argv(commands[args.name], values, args.args)
    started = time.monotonic()
    try:
        done = subprocess.run(argv, stdout=2, check=False)
    except OSError as exc:
        raise CliError("unavailable", f"{argv[0]} cannot run: {exc.strerror or exc}") from exc
    return {
        "name": args.name,
        "argv": argv,
        "exit": done.returncode,
        "seconds": round(time.monotonic() - started, 3),
        "ok": done.returncode == 0,
    }
