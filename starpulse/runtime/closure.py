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

from starpulse.board.model.adapter_types import ADAPTER_CONTEXTS, module_name
from starpulse.runtime import launch
from starpulse.runtime.config import Config, discover, load

SELF = "serve"

#: The module every run adapter's opt-in worker starts from, which reads what the runs worker reads.
_ADAPTER_ENTRY = "starpulse.runs.bin.adapter_worker"

#: The module each process starts from; its imports are what a change to the installed code can reach it through.
ENTRIES = {
    SELF: "starpulse.runtime.server",
    "api": "starpulse.views.bin.api_worker",
    "pulls": "starpulse.runtime.worker",
    "scheduler": "starpulse.scheduler.bin.scheduler_worker",
    "runs": "starpulse.runs.bin.runs_worker",
    "flow-metrics": "starpulse.flow_metrics.bin.flow_metrics_worker",
    "search": "starpulse.board.bin.search_worker",
    "board": "starpulse.board.bin.board_worker",
    **dict.fromkeys(ADAPTER_CONTEXTS, _ADAPTER_ENTRY),
}

_CHILDREN = tuple(name for name in ENTRIES if name != SELF)
#: The run adapters' opt-in workers, which read the runs config and the board as the runs worker does.
_BOARD_READERS = ("pulls", "scheduler", "runs", "flow-metrics", "board", *ADAPTER_CONTEXTS)


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
    """`contexts` plus the Page API, which is built from the whole config and so is replaced on any config change."""
    return ("api", *contexts)


#: Who reads each `starpulse.toml` top-level key: the children a reload replaces when it changes, or `SELF` for a key only
#: a restart of `serve` applies. The Page API swaps hot behind the shared socket, so it is listed beside every owner.
CONFIG_OWNERS: dict[str, tuple[str, ...]] = {
    "tracker_url": _owned_by(),
    "harnesses_file": _owned_by(),
    "analytics": _owned_by(),
    "telemetry_loki_url": _owned_by(),
    "cursor_context": _owned_by(),
    "producers": _owned_by(),
    "project": _owned_by(),
    "database_url": _CHILDREN,
    "board": _owned_by(*_BOARD_READERS),
    "runs": _owned_by("runs", *ADAPTER_CONTEXTS),
    "search": _owned_by("search"),
    "read_model": (SELF,),
    "release": _owned_by("pulls"),
    "repos": _owned_by("pulls"),
    "pull_requests": _owned_by("pulls"),
    "ci": _owned_by("pulls"),
    "sequences": _owned_by("pulls"),
    "scheduler": _owned_by("scheduler"),
    "level": _owned_by("scheduler"),
    "session_start_url": _owned_by("scheduler"),
    "event_log_retention_days": _owned_by("flow-metrics"),
    "event_log_archive_dir": _owned_by("flow-metrics"),
    **dict.fromkeys(_SERVE_KEYS, (SELF,)),
}


def restarts_serve(old: Mapping[str, object], new: Mapping[str, object]) -> bool:
    """Whether a change from the `old` to the `new` raw `starpulse.toml` needs `serve` itself restarted.

    True when a changed key is one only `serve` reads, one no owner is named for, or one that adds or drops a supervised child:
    a search `embeddings_url`. Any other change is applied by replacing the children that own it."""
    changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    if any(SELF in CONFIG_OWNERS.get(key, (SELF,)) for key in changed):
        return True
    return bool(_embeddings_url(old)) != bool(_embeddings_url(new))


def _embeddings_url(raw: Mapping[str, object]) -> object:
    search = raw.get("search")
    return search.get("embeddings_url") if isinstance(search, Mapping) else None


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


def _blocks(name: str, config: Config) -> tuple[object, object]:
    """The (restart, live) config blocks of `name`: the ones a running worker needs a new process for, and the ones it
    re-reads on `SIGHUP`. `serve` itself has none.

    Each context's blocks are imported here, not at the top, so a worker's import closure holds no other context's."""
    from starpulse.board.bin.blocks import board_built_blocks, search_built_blocks
    from starpulse.flow_metrics.bin.blocks import flow_metrics_built_blocks
    from starpulse.pulls.bin.blocks import pulls_delivery_blocks, pulls_fixed_blocks
    from starpulse.runs.bin.blocks import runs_built_blocks
    from starpulse.scheduler.bin.blocks import scheduler_fixed_blocks, scheduler_live_blocks
    from starpulse.views.bin.blocks import api_built_blocks

    if name == "api":
        return api_built_blocks(config), ()
    if name == "pulls":
        return pulls_fixed_blocks(config), pulls_delivery_blocks(config)
    if name == "scheduler":
        return scheduler_fixed_blocks(config), scheduler_live_blocks(config)
    if name == "runs" or name in ADAPTER_CONTEXTS:
        return runs_built_blocks(config), ()
    if name == "flow-metrics":
        return flow_metrics_built_blocks(config), ()
    if name == "search":
        return search_built_blocks(config), ()
    if name == "board":
        return board_built_blocks(config), ()
    return (), ()


class Reader:
    """The `Reading` of `serve` and of each worker, from the installed code and the config at `config_path`."""

    def __init__(self, config_path: Path | None) -> None:
        self._path = discover(config_path)
        self._hashes: dict[str, str] | None = None

    def _config(self) -> Config:
        try:
            return load(self._path)
        except (OSError, ValueError) as exc:
            raise ReloadError(f"{self._path}: {exc}") from exc

    def _blocks(self, name: str) -> tuple[object, object]:
        return _blocks(name, self._config())

    def at_start(self, name: str) -> Reading:
        """The reading of `name` as `serve` starts it: its config blocks and the hash of each module file, no closure."""
        if self._hashes is None:
            self._hashes = package_hashes()
        return Reading(frozenset(), *self._blocks(name), files=self._hashes)

    def __call__(self, name: str) -> Reading:
        config = self._config()
        # a worker's main takes the root config loader from `runtime` (spec doc-966, D6), so its entry imports none
        code = code_of(ENTRIES[name], extra=("starpulse.runtime.config", adapter_module(config.board_type)))
        return Reading(code, *_blocks(name, config))
