"""What a `starpulse` process runs from, read so `starpulse reload` can tell which process a change reaches.

A process is its import closure (the files of the `starpulse` modules its entry loads, with their content hashes) and the
config blocks it is built from. `code_of` reads the closure from the installed code in a fresh interpreter, as the
supervisor's children do when they start, so it sees what a child started now would load rather than what this process
has already imported.

`serve` starts without reading any closure: its start `Reading` holds `package_hashes`, the hash of every module file,
and a closure is unchanged since then while each of its files still has the hash it had.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from starpulse._internal.config.config import Config, discover, load

SELF = "serve"

#: The module each process starts from; its imports are what a change to the installed code can reach it through.
ENTRIES = {
    SELF: "starpulse._internal.server.server",
    "api": "starpulse._internal.server.api_worker",
    "pulls": "starpulse._internal.server.worker",
    "scheduler": "starpulse._internal.server.scheduler_worker",
    "runs": "starpulse._internal.server.runs_worker",
    "flow-metrics": "starpulse._internal.server.flow_metrics_worker",
    "search": "starpulse._internal.server.search_worker",
    "board": "starpulse._internal.server.board_worker",
}

_CHILDREN = tuple(name for name in ENTRIES if name != SELF)
_BOARD_READERS = ("pulls", "scheduler", "runs", "flow-metrics", "board")


#: The keys `serve` alone reads: whether each child runs, its memory limit, and its refresh token.
_SERVE_KEYS = (
    "mode",
    "refresh_token_env",
    "slow_read_seconds",
    "worker_memory",
    "api_worker",
    "runs_worker",
    "flow_metrics_worker",
    "search_worker",
    "board_worker",
)


def _owned_by(*contexts: str) -> tuple[str, ...]:
    """`contexts` plus the Page API, which is built from the whole config and so is replaced on any config change."""
    return ("api", *contexts)


#: Who reads each `starpulse.toml` top-level key: the children a reload replaces when it changes, or `SELF` for a key only
#: a restart of `serve` applies. The Page API swaps hot behind the shared socket, so it is listed beside every owner.
CONFIG_OWNERS: dict[str, tuple[str, ...]] = {
    "tracker_url": _owned_by(),
    "harnesses_file": _owned_by(),
    "tls_cert": _owned_by(),
    "tls_key": _owned_by(),
    "analytics": _owned_by(),
    "cursor_context": _owned_by(),
    "producers": _owned_by(),
    "project": _owned_by(),
    "database_url": _CHILDREN,
    "board": _owned_by(*_BOARD_READERS),
    "runs": _owned_by("runs"),
    "search": _owned_by("search"),
    "release": _owned_by("pulls"),
    "repos": _owned_by("pulls"),
    "pull_requests": _owned_by("pulls"),
    "ci": _owned_by("pulls"),
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
    files: Mapping[str, str] | None = None  # a start reading: the hash of every module file, in place of a closure

    def same_code(self, after: Reading) -> bool:
        """Whether the closure in `after` is what this reading ran from."""
        if self.files is None:
            return self.code == after.code
        return all(self.files.get(file) == digest for file, digest in after.code)


def package_hashes(package: str = "starpulse") -> dict[str, str]:
    """The content hash of each module file under `package` as installed, which no interpreter has to import to read.

    Raises `ReloadError` when `package` is not installed or a file cannot be read."""
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        raise ReloadError(f"{package} is not installed")
    suffixes = (".py", *importlib.machinery.EXTENSION_SUFFIXES)
    try:
        return {
            str(file): sha256(file.read_bytes()).hexdigest()
            for root in spec.submodule_search_locations
            for file in Path(root).rglob("*")
            if file.name.endswith(suffixes)
        }
    except OSError as exc:
        raise ReloadError(f"{package}: {exc}") from exc


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
    from starpulse._internal.server import (  # noqa: PLC0415 - imported only when read
        api_worker,
        scheduler_worker,
        board_worker,
        flow_metrics_worker,
        runs_worker,
        search_worker,
        worker,
    )

    if name == "api":
        return api_worker.built_blocks(config), ()
    if name == "pulls":
        return worker.fixed_blocks(config), worker.delivery_blocks(config)
    if name == "scheduler":
        return scheduler_worker.fixed_blocks(config), scheduler_worker.scheduler_blocks(config)
    if name == "runs":
        return runs_worker.built_blocks(config), ()
    if name == "flow-metrics":
        return flow_metrics_worker.built_blocks(config), ()
    if name == "search":
        return search_worker.built_blocks(config), ()
    if name == "board":
        return board_worker.built_blocks(config), ()
    return (), ()


class Reader:
    """The `Reading` of `serve` and of each worker, from the installed code and the config at `config_path`."""

    def __init__(self, config_path: Path | None) -> None:
        self._path = discover(config_path)
        self._hashes: dict[str, str] | None = None

    def _blocks(self, name: str) -> tuple[object, object]:
        try:
            config = load(self._path)
        except (OSError, ValueError) as exc:
            raise ReloadError(f"{self._path}: {exc}") from exc
        return _blocks(name, config)

    def at_start(self, name: str) -> Reading:
        """The reading of `name` as `serve` starts it: its config blocks and the hash of each module file, no closure."""
        if self._hashes is None:
            self._hashes = package_hashes()
        return Reading(frozenset(), *self._blocks(name), files=self._hashes)

    def __call__(self, name: str) -> Reading:
        blocks = self._blocks(name)
        return Reading(code_of(ENTRIES[name]), *blocks)
