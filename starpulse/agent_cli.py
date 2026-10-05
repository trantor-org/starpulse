"""`starpulse snapshot|board|task show|help --agent`: the verbs an agent reads a running StarPulse server with.

    starpulse board --milestone launch --label api
    starpulse task show PROJ-45
    starpulse help --agent

Every verb writes one JSON document to stdout, an error as `{"error": "...", "code": "..."}`, and nothing to stderr.
The exit code is 0 for success, 1 for a refused or invalid request, 2 for a usage error, 3 when the server (or what the
verb needs of it) is unavailable and 4 for something not found. The server is `--server`, else `STARPULSE_URL`, else
`http://localhost:8766`; a verb reads it per call and keeps nothing. `starpulse help --agent` prints the manifest of
verbs, generated from the parser below, so a verb added here is listed with its arguments, output keys and exit codes.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any, NoReturn

#: serve's default `--port`, where a server runs unless the caller says otherwise.
DEFAULT_SERVER = "http://localhost:8766"
#: What each exit code means, as the manifest says it.
EXIT_CODES = {0: "ok", 1: "refused or invalid", 2: "usage", 3: "unavailable", 4: "not found"}
#: The exit code of each error `code`.
_ERROR_EXIT = {"refused": 1, "usage": 2, "unavailable": 3, "not_found": 4}

_SNAPSHOT_KEYS = (
    "graphs",
    "flows",
    "dags",
    "pulls",
    "claims",
    "settled",
    "error",
    "cues",
    "domains",
    "boardUrl",
    "now",
)
_TASK_KEYS = (
    "id",
    "title",
    "lane",
    "assignee",
    "milestone",
    "labels",
    "dependencies",
    "waiting_on",
    "prs",
    "moves",
    "description",
)

Verb = Callable[[argparse.Namespace, Mapping[str, str]], dict[str, Any]]


class CliError(Exception):
    """A request a verb cannot answer: `code` is one of `_ERROR_EXIT`, the message says why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _Parser(argparse.ArgumentParser):
    """A parser whose usage errors are `CliError`s, so they reach stdout as JSON instead of stderr as text."""

    def error(self, message: str) -> NoReturn:
        raise CliError("usage", message)


def server_url(flag: str | None, environ: Mapping[str, str]) -> str:
    """The server to read: the `--server` flag, else `STARPULSE_URL`, else the default, without a trailing slash."""
    return (flag or environ.get("STARPULSE_URL") or DEFAULT_SERVER).rstrip("/")


def _get(base: str, path: str) -> dict[str, Any]:
    """The JSON document the server at `base` answers `path` with."""
    try:
        with urllib.request.urlopen(
            f"{base}{path}",
            timeout=10.0,  # seconds the server may take to answer one read
        ) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise CliError("unavailable", f"{base} answered {exc.code} for {path}: is it a StarPulse server?") from exc
    except (OSError, ValueError) as exc:
        raise CliError("unavailable", f"cannot reach StarPulse at {base}: {exc}") from exc


def _snapshot(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    return _get(server_url(args.server, environ), "/api/snapshot")


def _board_flow(snapshot: dict[str, Any]) -> dict[str, Any]:
    return next(flow for flow in snapshot["flows"] if flow["name"] == "board")


def _task(agent: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """A Board task as a verb reports it. It waits on each dependency that has not completed."""
    pulls = {pull["url"]: pull for pull in snapshot["pulls"].get(agent["id"], [])}
    return {
        "id": agent["id"],
        "title": agent["title"],
        "lane": agent["state"],
        "assignee": agent["model"],
        "milestone": agent["milestone"],
        "labels": agent["labels"],
        "dependencies": agent["dependencies"],
        "waiting_on": [d for d in agent["dependencies"] if snapshot["settled"].get(d) != "completed"],
        "prs": [pulls.get(url, {"url": url}) for url in agent["prs"]],
        "moves": agent["moves"],
    }


def _board(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    snapshot = _snapshot(args, environ)
    board = _board_flow(snapshot)
    states = board["machine"]["states"]
    if args.state and args.state not in (ids := [s["id"] for s in states]):
        raise CliError("usage", f"unknown state {args.state}; the board has {', '.join(ids)}")

    def kept(agent: dict[str, Any]) -> bool:
        return (
            (not args.milestone or agent["milestone"] == args.milestone)
            and (not args.label or args.label in agent["labels"])
            and (not args.assignee or agent["model"] == args.assignee)
        )

    return {
        "columns": [
            {
                "state": state["id"],
                "name": state["name"],
                "tasks": [_task(a, snapshot) for a in board["agents"] if a["state"] == state["id"] and kept(a)],
            }
            for state in states
            if not args.state or state["id"] == args.state
        ]
    }


def _show(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    snapshot = _snapshot(args, environ)
    agents = {agent["id"]: agent for agent in _board_flow(snapshot)["agents"]}
    if (agent := agents.get(args.task)) is None:
        if (lane := snapshot["settled"].get(args.task)) is None:
            raise CliError("not_found", f"{args.task} is not on the board")
        # A settled task has left the lanes, and the snapshot keeps only where it settled.
        agent = {
            "id": args.task,
            "title": "",
            "state": lane,
            "model": "",
            "milestone": "",
            "labels": [],
            "dependencies": [],
            "prs": [],
            "moves": {},
            "description": "",
        }
    return {**_task(agent, snapshot), "description": agent["description"]}


def _help(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    return _manifest(_parser())


def _leaves(
    parser: argparse.ArgumentParser, path: tuple[str, ...] = ()
) -> Iterator[tuple[str, argparse.ArgumentParser]]:
    """Each verb the parser dispatches to, as its words (`task show`) and its own parser."""
    for action in parser._actions:  # argparse offers no public way to list a parser's subcommands
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from _leaves(sub, (*path, name))
            return
    yield " ".join(path), parser


def _manifest(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """Every verb with its arguments, output keys and exit codes, read off the parser."""
    return {
        "exit_codes": {str(code): meaning for code, meaning in EXIT_CODES.items()},
        "verbs": [
            {
                "verb": verb,
                "summary": leaf.description,
                "arguments": [
                    {"name": a.dest, "flags": a.option_strings, "required": a.required, "help": a.help}
                    for a in leaf._actions
                    if a.dest != "help"
                ],
                "outputs": leaf.get_default("outputs"),
                "exit_codes": leaf.get_default("exit_codes"),
            }
            for verb, leaf in _leaves(parser)
        ],
    }


@functools.cache
def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="starpulse",
        description="StarPulse: the flow view of workflows and tasks. These verbs read a running server as JSON.",
        epilog="`starpulse serve` runs the server and `starpulse emit` pushes a workflow run; each has its own --help.",
    )
    verbs = parser.add_subparsers(dest="command", required=True, metavar="command")

    def leaf(
        group: argparse._SubParsersAction,
        name: str,
        summary: str,
        run: Verb,
        outputs: Sequence[str],
        exit_codes: Sequence[int],
        *,
        reads_server: bool = True,
    ) -> argparse.ArgumentParser:
        sub = group.add_parser(name, description=summary, help=summary, allow_abbrev=False)
        sub.set_defaults(run=run, outputs=list(outputs), exit_codes=list(exit_codes))
        if reads_server:
            sub.add_argument("--server", help=f"the server's address, else $STARPULSE_URL, else {DEFAULT_SERVER}")
        return sub

    leaf(
        verbs,
        "snapshot",
        "the server's whole snapshot: every machine with its tasks, workflows and pull requests",
        _snapshot,
        _SNAPSHOT_KEYS,
        (0, 2, 3),
    )
    board = leaf(
        verbs,
        "board",
        "the Board's tasks per column, each with its dependencies, pull requests and legal moves",
        _board,
        ("columns",),
        (0, 2, 3),
    )
    board.add_argument("--state", help="only this column, by its state id (`in_progress`)")
    board.add_argument("--milestone", help="only tasks in this milestone")
    board.add_argument("--label", help="only tasks with this label")
    board.add_argument("--assignee", help="only tasks held by this assignee (`@agent-standard-high`)")
    task = verbs.add_parser("task", description="one task of the Board", help="one task of the Board")
    task_verbs = task.add_subparsers(dest="verb", required=True, metavar="verb")
    show = leaf(
        task_verbs,
        "show",
        "one task: its lane, dependencies and what it still waits on, pull requests and legal moves",
        _show,
        _TASK_KEYS,
        (0, 2, 3, 4),
    )
    show.add_argument("task", help="the task's key (`PROJ-45`)")
    manifest = leaf(
        verbs,
        "help",
        "the verb manifest: verbs, arguments, output keys and exit codes",
        _help,
        ("exit_codes", "verbs"),
        (0, 2),
        reads_server=False,
    )
    manifest.add_argument("--agent", action="store_true", required=True, help="print the manifest as JSON")
    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] = os.environ) -> int:
    """Run one verb and print its JSON document; the exit code is the document's, as `EXIT_CODES` lists."""
    try:
        args = _parser().parse_args(argv)
        document, status = args.run(args, environ), 0
    except CliError as exc:
        document, status = {"error": str(exc), "code": exc.code}, _ERROR_EXIT[exc.code]
    print(json.dumps(document))
    return status
