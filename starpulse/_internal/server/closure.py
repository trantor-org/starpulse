"""What a `starpulse` process runs from, read so `starpulse reload` can tell which process a change reaches.

A process is its import closure (the files of the `starpulse` modules its entry loads, with their content hashes) and the
config blocks it is built from. `code_of` reads the closure from the installed code in a fresh interpreter, as the
supervisor's children do when they start, so it sees what a child started now would load rather than what this process
has already imported.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from starpulse._internal.config.config import Config, discover, load

SELF = "serve"

#: The module each process starts from; its imports are what a change to the installed code can reach it through.
ENTRIES = {
    SELF: "starpulse._internal.server.server",
    "pulls": "starpulse._internal.server.worker",
    "autopilot": "starpulse._internal.server.autopilot_worker",
    "runs": "starpulse._internal.server.runs_worker",
    "forwarding": "starpulse._internal.server.forwarding_worker",
    "history": "starpulse._internal.server.history_worker",
}

_PROBE = (
    "import importlib, sys; importlib.import_module(sys.argv[1]); "
    "sys.stdout.write('\\0'.join(sorted(m.__file__ for n, m in sys.modules.items() "
    "if (n == sys.argv[2] or n.startswith(sys.argv[2] + '.')) and getattr(m, '__file__', None))))"
)


class ReloadError(RuntimeError):
    """The installed code or the config could not be read, so nothing was replaced."""


@dataclass(frozen=True)
class Reading:
    """One process's code and config as read now."""

    code: frozenset[tuple[str, str]]
    restart: object  # config blocks a running process cannot take in place
    live: object  # config blocks a running process re-reads on `SIGHUP`


def code_of(entry: str, package: str = "starpulse") -> frozenset[tuple[str, str]]:
    """The file and content hash of each `package` module that importing `entry` loads, read in a fresh interpreter.

    Raises `ReloadError` when `entry` does not import or a file cannot be read."""
    done = subprocess.run([sys.executable, "-c", _PROBE, entry, package], capture_output=True, text=True, check=False)
    if done.returncode:
        raise ReloadError(f"{entry} does not import: {done.stderr.strip().splitlines()[-1:]}")
    try:
        return frozenset(
            (file, sha256(Path(file).read_bytes()).hexdigest()) for file in done.stdout.split("\0") if file
        )
    except OSError as exc:
        raise ReloadError(f"{entry}: {exc}") from exc


def _blocks(name: str, config: Config) -> tuple[object, object]:
    """The (restart, live) config blocks of `name`: the ones a running worker needs a new process for, and the ones it
    re-reads on `SIGHUP`. `serve` itself has none."""
    from starpulse._internal.server import autopilot_worker, forwarding_worker, history_worker, runs_worker, worker  # noqa: PLC0415 - imported only when read

    if name == "pulls":
        return worker.fixed_blocks(config), worker.delivery_blocks(config)
    if name == "autopilot":
        return autopilot_worker.fixed_blocks(config), autopilot_worker.autopilot_blocks(config)
    if name == "runs":
        return runs_worker.built_blocks(config), ()
    if name == "forwarding":
        return forwarding_worker.built_blocks(config), ()
    if name == "history":
        return history_worker.built_blocks(config), ()
    return (), ()


class Reader:
    """The `Reading` of `serve` and of each worker, from the installed code and the config at `config_path`."""

    def __init__(self, config_path: Path | None) -> None:
        self._path = discover(config_path)

    def __call__(self, name: str) -> Reading:
        try:
            config = load(self._path)
        except (OSError, ValueError) as exc:
            raise ReloadError(f"{self._path}: {exc}") from exc
        return Reading(code_of(ENTRIES[name]), *_blocks(name, config))
