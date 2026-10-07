"""`starpulse serve|emit|forward|<verb> ...` (or `python -m starpulse`): the package's command line.

`serve` runs the view (`starpulse.server`), `emit` pushes a workflow run onto the runs stream (`starpulse.adapters.runs.emit`) and
`forward` sets the opt-in that lets a person's name leave for a hub (`starpulse.forward`) and `connect` writes the
config's `[board]` for a tracker after checking it answers (`starpulse.connect`); each reads the rest of the
line with its own flags, so `starpulse serve --help` lists the server's. Any other word is a verb that reads the
running server as JSON (`starpulse.agent_cli`), and `starpulse help --agent` lists them.
"""

import sys
from collections.abc import Callable

from starpulse import agent_cli, connect, forward, server
from starpulse.adapters.runs import emit

COMMANDS: dict[str, Callable[[list[str]], int | None]] = {
    "serve": server.main,
    "emit": emit.main,
    "forward": forward.main,
    "connect": connect.main,
}


def main(argv: list[str] | None = None) -> int | None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in COMMANDS:
        return COMMANDS[argv[0]](argv[1:])
    return agent_cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
