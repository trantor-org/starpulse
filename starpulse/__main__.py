"""`starpulse serve|emit|forward|<verb> ...` (or `python -m starpulse`): the package's command line.

`serve` runs the view (`starpulse._internal.server.server`), `emit` pushes a workflow run onto the runs stream (`starpulse._internal.runs.emit`) and
`forward` sets the opt-in that lets a person's name leave for a hub (`starpulse._internal.hub.forward`), `connect` writes the
config's `[board]` for a tracker after checking it answers (`starpulse._internal.cli.connect`) and `import-history` adds a
board's earlier lane changes to the store (`starpulse._internal.server.history_import`); each reads the rest of the
line with its own flags, so `starpulse serve --help` lists the server's. Any other word is a verb that reads the
running server as JSON (`starpulse._internal.cli.agent_cli`), and `starpulse help --agent` lists them.
"""

import sys
from collections.abc import Callable

from starpulse._internal.runs import emit
from starpulse._internal.hub import forward
from starpulse._internal.server import history_import, server
from starpulse._internal.cli import agent_cli, connect

COMMANDS: dict[str, Callable[[list[str]], int | None]] = {
    "serve": server.main,
    "emit": emit.main,
    "forward": forward.main,
    "connect": connect.main,
    "import-history": history_import.main,
}


def main(argv: list[str] | None = None) -> int | None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in COMMANDS:
        return COMMANDS[argv[0]](argv[1:])
    return agent_cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
