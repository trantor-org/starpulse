"""Keep the machine registry in step with the definition files: the Board's machine and each file under the owner's
`.starpulse/machines/`.

`serve` calls it at start and the workers at start and on a config reload. A file that is already active changes nothing;
a changed one is activated with the Task `Remapped` events its `migrations` mapping asks for, or refused with the States
and Tasks it strands. Only the Board's machine moves Tasks, so only it is checked against the live ones.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from starpulse._internal.board.project_machines import DIRECTORY
from starpulse._internal.config.config import Config, discover, load
from starpulse._internal.machines.machine_definition import MachineDefinitionError, _read
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore
from starpulse.event_log.store.machine_registry import LiveTask, MachineRegistry

__all__ = ["REFUSED", "main", "sync_definitions"]

#: The exit status of `main` when the registry refuses a definition; the reason is on stderr.
REFUSED = 3

EVERY_TASK = 2**31 - 1


def sync_definitions(config: Config, base: Path) -> dict[str, str]:
    """Activate the Board's machine file (`[board] machine`) and each file in `base`'s machines directory; the hash
    active for each machine. Raises `MachineDefinitionError` on a file the registry refuses, leaving the others as they
    were."""
    engine = EventLog(database_url(config.database_url, base)).engine
    store = EventStore(engine)
    Projector(engine, store).catch_up()
    rows = ReadModel(engine).since(0, EVERY_TASK)
    # A Task whose stream only ever held `Archived` (a retired file with no import) has no State to carry or strand.
    live = [LiveTask(row["id"], row["state"], row["version"], row["archived"]) for row in rows if row["state"]]
    registry = MachineRegistry(engine, store)
    board = base / str(config.board["machine"]) if "machine" in config.board else None
    hashes: dict[str, str] = {}
    if board is not None:
        document = _read(board)
        hashes[document["name"]] = registry.activate(document, live)
    for path in sorted((base / DIRECTORY).glob("*.yaml")):
        if board is None or path.resolve() != board.resolve():
            document = _read(path)
            hashes[document["name"]] = registry.activate(document, [])
    return hashes


def main(argv: list[str] | None = None) -> int:
    """Run `sync_definitions` for the config at `--config` (found from the working directory without it), the way
    `serve` admits definitions without loading the database stack itself."""
    parser = argparse.ArgumentParser(prog="machine_sync")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    try:
        sync_definitions(load(discover(args.config)), args.config.parent if args.config else Path.cwd())
    except MachineDefinitionError as exc:
        print(exc, file=sys.stderr)
        return REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main())
