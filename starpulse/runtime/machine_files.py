"""`starpulse machines`: the definition files as an optional copy of the machines the store holds.

    starpulse machines import [PATH ...] [--config starpulse.toml]
    starpulse machines export [--out DIR] [--config starpulse.toml]

The store is the source of truth: no start or reload reads a definition file. `import` activates each `PATH` (default:
the Board's `[board] machine` file and each file in the config directory's `.starpulse/machines/`) as its machine's
active version, a first install's way to fill an empty store; `export` writes each active machine as `<name>.yaml`
under `DIR` (default `.starpulse/machines/`), one path per line.

A file the registry refuses exits 3 with the reason on stderr: the files before it stay in, those after it are not
read; a Board machine that
strands live Tasks exits 4 after the other files are in, and the active Board version stays.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

from starpulse.board.adapters.project_machines import DIRECTORY
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.machine_store import MachineStore
from starpulse.event_log.opening import database_url
from starpulse.event_log.store.machine_registry import TASK_MACHINE, StrandedTasks
from starpulse.machine_engine.adapters.machine_loader import read_document
from starpulse.machine_engine.model.machine_definition import MachineDefinitionError
from starpulse.runtime.config import Config, discover, load

__all__ = ["REFUSED", "STRANDED", "export_definitions", "import_definitions", "main"]

#: The exit status of `import` when the registry refuses a definition.
REFUSED = 3
#: The exit status of `import` when only the Board machine is refused for stranding live Tasks.
STRANDED = 4


def _machines(config: Config, base: Path) -> MachineStore:
    return MachineStore(EventLog(database_url(config.database_url, base)).engine)


def import_definitions(config: Config, base: Path, paths: Sequence[Path] | None = None) -> dict[str, str]:
    """Activate the machine each of `paths` defines (default: the Board's machine file and each file in `base`'s
    machines directory) and return the hash active for each. Raises `MachineDefinitionError` on a file the registry
    refuses: the files before it stay in, those after it are not read; a Board machine that strands Tasks raises
    `StrandedTasks` after the other files are in."""
    machines = _machines(config, base)
    if paths is None:
        board = base / str(config.board["machine"]) if "machine" in config.board else None
        paths = [*([board] if board else []), *(p for p in sorted((base / DIRECTORY).glob("*.yaml")) if not board or p.resolve() != board.resolve())]
    live = machines.live_tasks()
    hashes: dict[str, str] = {}
    stranded: StrandedTasks | None = None
    for path in paths:
        document = read_document(path)
        try:
            hashes[document["name"]] = machines.registry.activate(
                document, live if document["name"] == TASK_MACHINE else []
            )
        except StrandedTasks as exc:
            stranded = exc
    if stranded is not None:
        raise stranded
    return hashes


def export_definitions(config: Config, base: Path, out: Path) -> list[Path]:
    """Write each active machine's definition as `<name>.yaml` under `out`; the paths written."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, document in _machines(config, base).active_definitions().items():
        written.append(out / f"{name}.yaml")
        written[-1].write_text(yaml.safe_dump(dict(document), sort_keys=False))
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starpulse machines", description="export and import machine definitions")
    verbs = parser.add_subparsers(dest="verb", required=True)
    loading = verbs.add_parser("import", help="activate definition files as their machines' versions")
    loading.add_argument("paths", nargs="*", type=Path, help="default: the Board's file and .starpulse/machines/*.yaml")
    exporting = verbs.add_parser("export", help="write each active machine as <name>.yaml")
    exporting.add_argument("--out", type=Path, help="default: .starpulse/machines")
    for verb in (loading, exporting):
        verb.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    args = parser.parse_args(argv)
    path = discover(args.config)
    config = load(path)
    base = path.parent if path else Path.cwd()
    try:
        if args.verb == "export":
            print("\n".join(map(str, export_definitions(config, base, args.out or base / DIRECTORY))))
        else:
            for name, digest in import_definitions(config, base, args.paths or None).items():
                print(f"{name} {digest}")
    except StrandedTasks as exc:
        print(exc, file=sys.stderr)
        return STRANDED
    except MachineDefinitionError as exc:
        print(exc, file=sys.stderr)
        return REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main())
