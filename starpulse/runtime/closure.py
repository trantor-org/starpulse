"""What a `starpulse` process runs from, read so `starpulse reload` can tell which process a change reaches.

A process is its import closure (the files of the `starpulse` modules its entry loads, with their content hashes) and the
config blocks it is built from. `code_of` reads the closure from the installed code in a fresh interpreter on the
launcher (`starpulse.runtime.launch`), as the supervisor's children are started, so it sees what a child started now would
load rather than what this process has already imported, and the release a symlink now names rather than the one `serve`
started in. A file is named by its path under the directory holding the package, so the same code in two release
directories reads equal.

`serve` starts without reading any closure: its start `Reading` holds `package_hashes`, the hash of every module file,
and a closure is unchanged since then while each of its files still has the hash it had.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from starpulse.board.model.adapter_types import module_name
from starpulse.runtime import launch
from starpulse.runtime.config import Config, discover, load

SELF = "serve"

#: The module every run adapter's opt-in worker starts from, which reads what the runs worker reads.
_ADAPTER_ENTRY = "starpulse.runs.bin.adapter_worker"

#: The modules `starpulse worker contexts` loads for its threads, which `starpulse.runtime.worker` imports only when the
#: process runs: its closure is the union of theirs.
CONTEXT_ENTRIES = (
    "starpulse.runtime.contexts",
    "starpulse.pulls.bin.pulls_worker",
    "starpulse.scheduler.bin.scheduler_worker",
    "starpulse.runs.bin.runs_worker",
    "starpulse.flow_metrics.bin.flow_metrics_worker",
    "starpulse.board.bin.search_worker",
    "starpulse.board.bin.board_worker",
    "starpulse.harness_telemetry.adapters.inbound.claude_code",
    _ADAPTER_ENTRY,
)

#: The module each process starts from; its imports are what a change to the installed code can reach it through.
ENTRIES = {
    SELF: "starpulse.runtime.server",
    "api": "starpulse.views.bin.api_worker",
    "contexts": "starpulse.runtime.worker",
}

_CHILDREN = tuple(name for name in ENTRIES if name != SELF)


#: The keys `serve` alone reads: each child's memory limit, its refresh token and its take-over command,
#: and the certificate it wraps the shared listening socket in, which a hot swap behind that socket cannot change.
_SERVE_KEYS = (
    "host",
    "port",
    "hours",
    "tls_cert",
    "tls_key",
    "mode",
    "refresh_token_env",
    "github_token_env",
    "take_over_command",
    "slow_read_seconds",
    "worker_memory",
)


def _owned_by(*contexts: str) -> tuple[str, ...]:
    """The Page API, which is built from the whole config and so is replaced on any config change, then `contexts` when a
    key is read by any of the background contexts it runs."""
    return ("api", *contexts)


#: Who reads each `starpulse.toml` top-level key: the children a reload replaces when it changes, or `SELF` for a key only
#: a restart of `serve` applies. The Page API swaps hot behind the shared socket, so it is listed beside every owner.
CONFIG_OWNERS: dict[str, tuple[str, ...]] = {
    "tracker_url": _owned_by(),
    "harnesses_file": _owned_by(),
    "analytics": _owned_by(),
    "telemetry_loki_url": _owned_by(),
    "cursor_context": _owned_by(),
    "claude_code": _owned_by("contexts"),
    "github": _owned_by("contexts"),
    "producers": _owned_by(),
    "project": _owned_by(),
    "database_url": _CHILDREN,
    "board": _owned_by("contexts"),
    "runs": _owned_by("contexts"),
    "search": _owned_by("contexts"),
    "read_model": (SELF,),
    "release": _owned_by("contexts"),
    "repos": _owned_by("contexts"),
    "pull_requests": _owned_by("contexts"),
    "ci": _owned_by("contexts"),
    "sequences": _owned_by("contexts"),
    "scheduler": _owned_by("contexts"),
    "level": _owned_by("contexts"),
    "session_start_url": _owned_by("contexts"),
    "event_log_retention_days": _owned_by("contexts"),
    "event_log_archive_dir": _owned_by("contexts"),
    **dict.fromkeys(_SERVE_KEYS, (SELF,)),
}


def restarts_serve(old: Mapping[str, object], new: Mapping[str, object]) -> bool:
    """Whether a change from the `old` to the `new` raw `starpulse.toml` needs `serve` itself restarted.

    True when a changed key is one only `serve` reads or one no owner is named for. Any other change is applied by
    replacing the children that own it: the set of children does not depend on the config."""
    changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    return any(SELF in CONFIG_OWNERS.get(key, (SELF,)) for key in changed)


#: Imports each module in `argv[2:]` and prints the directory holding package `argv[1]`, then the file of each module of
#: the package that is loaded, and of each named one, separated by NUL.
_PROBE = (
    "import importlib, os, sys; pkg, *entries = sys.argv[1:]; [importlib.import_module(e) for e in entries]; "
    "root = os.path.dirname(os.path.dirname(sys.modules[pkg].__file__)); "
    "sys.stdout.write('\\0'.join([root, *sorted(m.__file__ for n, m in sys.modules.items() "
    "if (n == pkg or n.startswith(pkg + '.') or n in entries) and getattr(m, '__file__', None))]))"
)


class ReloadError(RuntimeError):
    """The installed code or the config could not be read, so nothing was replaced."""


@dataclass(frozen=True)
class Reading:
    """One process's code and config as read now."""

    code: frozenset[tuple[str, str]]
    restart: object  # config blocks a running process cannot take in place
    live: object  # config blocks a running process re-reads on `SIGHUP`
    files: Mapping[str, str] | None = None  # a start reading: the hash of every module file, in place of a closure

    def same_code(self, after: Reading) -> bool:
        """Whether the closure in `after` is what this reading ran from."""
        if self.files is None:
            return self.code == after.code
        return all(self.files.get(file) == digest for file, digest in after.code)


def _name(file: str | Path, root: str | Path) -> str:
    """`file` under the directory `root` holds the package in, else as given."""
    relative = os.path.relpath(file, root)
    return str(file) if relative.startswith("..") else relative


def package_hashes(package: str = "starpulse") -> dict[str, str]:
    """The content hash of each module file under `package` as installed, which no interpreter has to import to read.

    Raises `ReloadError` when `package` is not installed or a file cannot be read."""
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        raise ReloadError(f"{package} is not installed")
    suffixes = (".py", *importlib.machinery.EXTENSION_SUFFIXES)
    try:
        return {
            _name(file, Path(root).parent): sha256(file.read_bytes()).hexdigest()
            for root in spec.submodule_search_locations
            for file in Path(root).rglob("*")
            if file.name.endswith(suffixes)
        }
    except OSError as exc:
        raise ReloadError(f"{package}: {exc}") from exc


def code_of(entry: str, package: str = "starpulse", extra: tuple[str, ...] = ()) -> frozenset[tuple[str, str]]:
    """The file and content hash of each `package` module that importing `entry` and each `extra` module loads, read in a
    fresh interpreter on the launcher.

    Raises `ReloadError` when a module does not import or a file cannot be read."""
    done = subprocess.run(
        [launch.interpreter(), "-c", _PROBE, package, entry, *extra], capture_output=True, text=True, check=False
    )
    if done.returncode:
        raise ReloadError(f"{entry} does not import: {done.stderr.strip().splitlines()[-1:]}")
    root, *files = done.stdout.split("\0")
    try:
        return frozenset((_name(file, root), sha256(Path(file).read_bytes()).hexdigest()) for file in files if file)
    except OSError as exc:
        raise ReloadError(f"{entry}: {exc}") from exc


def adapter_module(board_type: str) -> str:
    """The module `board_type` maps to in `adapter_types`. `config` imports the board adapter lazily, so no entry's import
    closure holds it and an edit to it would reach no child unless it is read with the closure.

    Raises `ReloadError` when the type names no module."""
    try:
        return module_name(board_type)
    except ValueError as exc:
        raise ReloadError(f"board type {board_type}: {exc}") from exc


def _machine_hash(config: Config, base: Path) -> str:
    """The content hash of the Board machine file `[board] machine` names, which a worker compiles once at start: a merged
    change to it replaces the worker, as the file's path alone never changes. Empty when the board names none."""
    file = config.board.get("machine")
    if file is None:
        return ""
    try:
        return sha256((base / str(file)).read_bytes()).hexdigest()
    except OSError as exc:
        raise ReloadError(f"board machine {file}: {exc}") from exc


def _blocks(name: str, config: Config, base: Path) -> tuple[object, object]:
    """The (restart, live) config blocks of `name`: the ones a running worker needs a new process for, and the ones it
    re-reads on `SIGHUP`, with the hash of the Board machine file it builds. `serve` itself has none.

    Each context's blocks are imported here, not at the top, so a worker's import closure holds no other context's."""
    from starpulse.board.bin.blocks import board_built_blocks, search_built_blocks
    from starpulse.flow_metrics.bin.blocks import flow_metrics_built_blocks
    from starpulse.pulls.bin.blocks import pulls_delivery_blocks, pulls_fixed_blocks
    from starpulse.runs.bin.blocks import runs_built_blocks
    from starpulse.scheduler.bin.blocks import scheduler_fixed_blocks, scheduler_live_blocks
    from starpulse.views.bin.blocks import api_built_blocks

    if name == "api":
        try:
            return (api_built_blocks(config), _machine_hash(config, base)), ()
        except OSError as exc:  # the certificate or key being renewed
            raise ReloadError(f"api: {exc}") from exc
    if name == "contexts":
        restart = (
            pulls_fixed_blocks(config),
            scheduler_fixed_blocks(config),
            runs_built_blocks(config),
            flow_metrics_built_blocks(config),
            search_built_blocks(config),
            board_built_blocks(config),
            config.claude_code,
            _machine_hash(config, base),
        )
        return restart, (pulls_delivery_blocks(config), scheduler_live_blocks(config))
    return (), ()


class Reader:
    """The `Reading` of `serve` and of each worker, from the installed code and the config at `config_path`."""

    def __init__(self, config_path: Path | None) -> None:
        self._path = discover(config_path)
        self._base = self._path.parent if self._path else Path.cwd()
        self._hashes: dict[str, str] | None = None

    def _config(self) -> Config:
        try:
            return load(self._path)
        except (OSError, ValueError) as exc:
            raise ReloadError(f"{self._path}: {exc}") from exc

    def _blocks(self, name: str) -> tuple[object, object]:
        return _blocks(name, self._config(), self._base)

    def at_start(self, name: str) -> Reading:
        """The reading of `name` as `serve` starts it: its config blocks and the hash of each module file, no closure."""
        if self._hashes is None:
            self._hashes = package_hashes()
        return Reading(frozenset(), *self._blocks(name), files=self._hashes)

    def __call__(self, name: str) -> Reading:
        config = self._config()
        # a worker's main takes the root config loader from `runtime` (spec doc-966, D6), so its entry imports none
        extra = CONTEXT_ENTRIES if name == "contexts" else ()
        code = code_of(ENTRIES[name], extra=("starpulse.runtime.config", adapter_module(config.board_type), *extra))
        return Reading(code, *_blocks(name, config, self._base))
