"""Keep the machine registry in step with the definition files: the Board's machine and each file under the owner's
`.starpulse/machines/`.

`serve` calls it at start and the workers at start and on a config reload. A file imports only a machine the store has
never held a version of: once it has one, the store is the source and the file never overwrites it, so an edit made
through the API survives a restart. A first import of the Board's machine is checked against the live Tasks (a file that
strands them raises `StrandedTasks`, once the other files are synced).
"""

import argparse
import sys
from pathlib import Path

from starpulse.runtime.config import Config, discover, load
from starpulse.board.adapters.project_machines import DIRECTORY
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.machine_store import MachineStore
from starpulse.event_log.opening import database_url
from starpulse.event_log.store import EventStore
from starpulse.event_log.store.machine_registry import LiveTask, StrandedTasks
from starpulse.machine_engine.adapters.machine_loader import read_document
from starpulse.machine_engine.model.machine_definition import MachineDefinitionError

__all__ = ["REFUSED", "STRANDED", "main", "sync_definitions"]

#: The exit status of `main` when the registry refuses a definition; the reason is on stderr.
REFUSED = 3

#: The exit status of `main` when only a Board machine change that strands live Tasks is refused: the active version
#: stays, and every other definition file was still synced.
STRANDED = 4


def sync_definitions(config: Config, base: Path) -> dict[str, str]:
    """Import the Board's machine file (`[board] machine`) and each file in `base`'s machines directory whose machine
    the store has no version of; the hash active for each machine the store runs. Raises `MachineDefinitionError` on a
    file the registry refuses, leaving the others as they were; a Board machine that strands Tasks raises
    `StrandedTasks` after the other files are synced."""
    engine = EventLog(database_url(config.database_url, base)).engine
    store = EventStore(engine)
    machines = MachineStore(engine, store)
    live = machines.live_tasks()
    board = base / str(config.board["machine"]) if "machine" in config.board else None
    hashes: dict[str, str] = {}
    stranded: StrandedTasks | None = None
    if board is not None:
        document = read_document(board)
        try:
            _import(machines, document, live, hashes)
        except StrandedTasks as exc:
            stranded = exc
    for path in sorted((base / DIRECTORY).glob("*.yaml")):
        if board is None or path.resolve() != board.resolve():
            _import(machines, read_document(path), [], hashes)
    if stranded is not None:
        raise stranded
    return hashes


def _import(machines: MachineStore, document: dict, live: list[LiveTask], hashes: dict[str, str]) -> None:
    name = document["name"]
    if not machines.imported(name):
        hashes[name] = machines.registry.activate(document, live)
    elif (held := machines.active_hash(name)) is not None:
        hashes[name] = held


def main(argv: list[str] | None = None) -> int:
    """Run `sync_definitions` for the config at `--config` (found from the working directory without it), the way
    `serve` admits definitions without loading the database stack itself."""
    parser = argparse.ArgumentParser(prog="machine_sync")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    try:
        path = discover(args.config)
        sync_definitions(load(path), path.parent if path else Path.cwd())
    except StrandedTasks as exc:
        print(exc, file=sys.stderr)
        return STRANDED
    except MachineDefinitionError as exc:
        print(exc, file=sys.stderr)
        return REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main())
