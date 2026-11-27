"""`starpulse serve|<verb> ...` (or `python -m starpulse`): the package's command line.

`serve` runs the view (`starpulse.runtime.server`), `init` scaffolds a first install (`starpulse.cli.init`),
`event emit` publishes one CloudEvent to the JetStream ingest (`starpulse.cli.event`), `github requeue|dismiss|restore|purge|retire` settles a dead GitHub
delivery (`starpulse.cli.github_inbox`), `migrate` brings the store to its
schema (`starpulse.runtime.store_migrate`), `rehearse` starts `serve` on a copy of a store and waits for `/api/health`
(`starpulse.runtime.rehearse`), `import-history` adds a
board's earlier lane changes to the store (`starpulse.runtime.history_import`), and `conform` replays the recorded
history against the machines the project declares (`starpulse.runtime.conform`); each reads the rest of the
line with its own flags, so `starpulse serve --help` lists the server's. Any other word is a verb that reads the
running server as JSON (`starpulse.cli.agent_cli`), and `starpulse help --agent` lists them.
"""

import importlib
import sys
from collections.abc import Callable

lazy from starpulse.cli import agent_cli


def _lazy(module: str) -> Callable[[list[str]], int | None]:
    """A subcommand's `main`, imported when it runs: an agent verb never pays for the server's or the event log's imports."""

    def run(argv: list[str]) -> int | None:
        return importlib.import_module(module).main(argv)

    return run


COMMANDS: dict[str, Callable[[list[str]], int | None]] = {
    "serve": _lazy("starpulse.runtime.server"),
    "init": _lazy("starpulse.cli.init"),
    "event": _lazy("starpulse.cli.event"),
    "github": _lazy("starpulse.cli.github_inbox"),
    "worker": _lazy("starpulse.runtime.worker"),
    "migrate": _lazy("starpulse.runtime.store_migrate"),
    "replay": _lazy("starpulse.runtime.store_replay"),
    "parity": _lazy("starpulse.runtime.parity"),
    "rehearse": _lazy("starpulse.runtime.rehearse"),
    "import-history": _lazy("starpulse.runtime.history_import"),
    "import-board": _lazy("starpulse.runtime.board_import"),
    "conform": _lazy("starpulse.runtime.conform"),
    "policy": _lazy("starpulse.runtime.policy"),
    "machines": _lazy("starpulse.runtime.machine_files"),
    "reload": _lazy("starpulse.runtime.control"),
    "backup": _lazy("starpulse.runtime.backup"),
    "mcp": _lazy("starpulse.cli.lane_mcp"),
}


def main(argv: list[str] | None = None) -> int | None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in COMMANDS:
        if argv[0] == "worker":
            from starpulse.runtime.hold import watch_supervisor

            watch_supervisor()
        return COMMANDS[argv[0]](argv[1:])

    return agent_cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
