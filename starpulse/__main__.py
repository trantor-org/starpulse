"""`starpulse serve|emit ...` (or `python -m starpulse`): the package's command line.

`serve` runs the view (`starpulse.server`) and `emit` pushes a workflow run onto the runs stream (`starpulse.emit`);
each reads the rest of the line with its own flags, so `starpulse serve --help` lists the server's.
"""

import argparse
import sys
from collections.abc import Callable

from starpulse import emit, server

COMMANDS: dict[str, Callable[[list[str]], int | None]] = {"serve": server.main, "emit": emit.main}


def main(argv: list[str] | None = None) -> int | None:
    parser = argparse.ArgumentParser(prog="starpulse", description="StarPulse: the flow view of workflows and tasks")
    parser.add_argument("command", choices=COMMANDS, help="serve: run the view; emit: push a workflow run event")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="the subcommand's own flags")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    return COMMANDS[args.command](args.args)


if __name__ == "__main__":
    raise SystemExit(main())
