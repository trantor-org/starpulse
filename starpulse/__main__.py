"""`starpulse serve|emit|forward|<verb> ...` (or `python -m starpulse`): the package's command line.

`serve` runs the view (`starpulse._internal.server.server`), `emit` pushes a workflow run onto the runs stream (`starpulse._internal.runs.emit`) and
`forward` sets the opt-in that lets a person's name leave for a hub (`starpulse._internal.hub.forward`), `connect` writes the
config's `[board]` for a tracker after checking it answers (`starpulse._internal.cli.connect`) and `import-history` adds a
board's earlier lane changes to the store (`starpulse._internal.server.history_import`); each reads the rest of the
line with its own flags, so `starpulse serve --help` lists the server's. Any other word is a verb that reads the
running server as JSON (`starpulse._internal.cli.agent_cli`), and `starpulse help --agent` lists them.
"""

import importlib
import sys
from collections.abc import Callable

from starpulse._internal.cli import agent_cli


def _lazy(module: str) -> Callable[[list[str]], int | None]:
    """A subcommand's `main`, imported when it runs: an agent verb never pays for the server's or the event log's imports."""

    def run(argv: list[str]) -> int | None:
        return importlib.import_module(module).main(argv)

    return run


COMMANDS: dict[str, Callable[[list[str]], int | None]] = {
    "serve": _lazy("starpulse._internal.server.server"),
    "emit": _lazy("starpulse._internal.runs.emit"),
    "forward": _lazy("starpulse._internal.hub.forward"),
    "connect": _lazy("starpulse._internal.cli.connect"),
    "worker": _lazy("starpulse._internal.server.worker"),
    "import-history": _lazy("starpulse._internal.server.history_import"),
    "reload": _lazy("starpulse._internal.server.control"),
}


def main(argv: list[str] | None = None) -> int | None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in COMMANDS:
        return COMMANDS[argv[0]](argv[1:])
    return agent_cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
