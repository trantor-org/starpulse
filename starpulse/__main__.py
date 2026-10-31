"""`starpulse serve|<verb> ...` (or `python -m starpulse`): the package's command line.

`serve` runs the view (`starpulse.runtime.server`), `init` scaffolds a first install (`starpulse.cli.init`),
`event emit` posts one CloudEvent to the ingest (`starpulse.cli.event`), `connect` writes the
config's `[board]` for a tracker after checking it answers (`starpulse.cli.connect`), `migrate` brings the store to its
schema (`starpulse.runtime.store_migrate`), `import-history` adds a
board's earlier lane changes to the store (`starpulse.runtime.history_import`), `backfill-telemetry` copies the event
log's telemetry signals into Loki (`starpulse.runtime.telemetry_backfill`) and `conform` replays the recorded
history against the machines the project declares (`starpulse.runtime.conform`); each reads the rest of the
line with its own flags, so `starpulse serve --help` lists the server's. Any other word is a verb that reads the
running server as JSON (`starpulse.cli.agent_cli`), and `starpulse help --agent` lists them.
"""

import importlib
import sys
from collections.abc import Callable


def _lazy(module: str) -> Callable[[list[str]], int | None]:
    """A subcommand's `main`, imported when it runs: an agent verb never pays for the server's or the event log's imports."""

    def run(argv: list[str]) -> int | None:
        return importlib.import_module(module).main(argv)

    return run


COMMANDS: dict[str, Callable[[list[str]], int | None]] = {
    "serve": _lazy("starpulse.runtime.server"),
    "init": _lazy("starpulse.cli.init"),
    "connect": _lazy("starpulse.cli.connect"),
    "event": _lazy("starpulse.cli.event"),
    "worker": _lazy("starpulse.runtime.worker"),
    "migrate": _lazy("starpulse.runtime.store_migrate"),
    "import-history": _lazy("starpulse.runtime.history_import"),
    "import-board": _lazy("starpulse.runtime.board_import"),
    "conform": _lazy("starpulse.runtime.conform"),
    "reload": _lazy("starpulse.runtime.control"),
    "backup": _lazy("starpulse.runtime.backup"),
    "backfill-telemetry": _lazy("starpulse.runtime.telemetry_backfill"),
}


def main(argv: list[str] | None = None) -> int | None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in COMMANDS:
        if argv[0] == "worker":
            from starpulse.runtime.hold import watch_supervisor

            watch_supervisor()
        return COMMANDS[argv[0]](argv[1:])
    from starpulse.cli import agent_cli  # noqa: PLC0415 - import cost, paid only by a verb that reads the server

    return agent_cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
