"""`starpulse serve|emit|<verb> ...` (or `python -m starpulse`): the package's command line.

`serve` runs the view (`starpulse.server`) and `emit` pushes a workflow run onto the runs stream (`starpulse.emit`);
each reads the rest of the line with its own flags, so `starpulse serve --help` lists the server's. Any other word is
a verb that reads the running server as JSON (`starpulse.agent_cli`), and `starpulse help --agent` lists them.
"""

import sys
from collections.abc import Callable

from starpulse import agent_cli, emit, server

COMMANDS: dict[str, Callable[[list[str]], int | None]] = {"serve": server.main, "emit": emit.main}


def main(argv: list[str] | None = None) -> int | None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in COMMANDS:
        return COMMANDS[argv[0]](argv[1:])
    return agent_cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
