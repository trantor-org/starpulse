"""StarPulse's one config file: its board adapter, its history database, and which runs adapters run.

Database credentials never live here; they come from the driver's environment, such as `PGPASSWORD`.
With no file the view runs as an individual-contributor view of its own
Markdown board in `./.starpulse/board`, keeping its history in a SQLite file, with no runs adapter.

The `[board]` table names the board adapter by `type` (`starpulse.board`); the rest of the table is that
adapter's settings. `database_url` is the SQLAlchemy URL of the history store (`starpulse.history`).

Each `[[runs]]` table is one instance of a runs adapter: its `name`, the adapter module `type` (a name under
`starpulse`, or the dotted path of a module an installed package provides), the `url` it reads, the workflows Run now may start (`run_safe`) and the `domains` that
group its workflows on the page, and optionally `token_env`, the name of the environment variable that holds the
token the HTTP ingest accepts for it (the token itself is never in this file). A workflow is shown as `<instance>/<workflow>`, so two instances can
carry the same workflow name.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from starpulse.board import DEFAULT_TYPE, module_name
from starpulse.harnesses import Harnesses, load_harnesses

_KEYS = {"tracker_url", "mode", "runs", "harnesses_file", "board", "database_url", "session_start_url"}
_INSTANCE_KEYS = {"name", "type", "url", "run_safe", "domains", "token_env"}

_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

__all__ = ["Config", "ConfigError", "RunsInstance", "load", "runs_adapter"]


class ConfigError(ValueError):
    """The config file is not one the view can run from; `unknown_keys` names the keys it refused as unknown."""

    def __init__(self, message: str, unknown_keys: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.unknown_keys = tuple(unknown_keys)


def _names(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(name, str) for name in value)


@dataclass(frozen=True)
class RunsInstance:
    """One configured runs adapter: the workflows it lists are shown as `<name>/<workflow>`."""

    name: str
    type: str
    """The adapter module that reads the instance: a name under `starpulse`, or a dotted module path."""
    url: str
    run_safe: tuple[str, ...] = ()
    """The workflows Run now may start; any other answers 404, so none is startable by default."""
    domains: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """The page's groups of this instance's workflows, in the order it lays them out."""
    token_env: str | None = None
    """The environment variable holding this instance's ingest token; none: the instance takes no pushed events."""


def runs_adapter(kind: str) -> ModuleType:
    """The runs adapter module `kind` names, which offers `start(url)` and `follow(url, runs, log)`."""
    if not isinstance(kind, str) or not all(part.isidentifier() for part in kind.split(".")):
        raise ConfigError(f"no runs adapter of type {kind}")
    target = module_name(kind)
    try:
        module = importlib.import_module(target)
    except ModuleNotFoundError as exc:
        if exc.name and (target == exc.name or target.startswith(f"{exc.name}.")):
            raise ConfigError(f"no runs adapter of type {kind}") from exc
        raise ConfigError(f"runs adapter {kind} failed to import: {exc}") from exc
    except ImportError as exc:
        raise ConfigError(f"runs adapter {kind} failed to import: {exc}") from exc
    if not (callable(getattr(module, "start", None)) and callable(getattr(module, "follow", None))):
        raise ConfigError(f"{kind} is not a runs adapter: it needs start(url) and follow(url, runs, log)")
    return module


def _instance(raw: object) -> RunsInstance:
    if not isinstance(raw, dict):
        raise ConfigError("runs must be a list of [[runs]] tables")
    for key in ("name", "type", "url"):
        if key not in raw:
            raise ConfigError(f"a runs instance needs {key}")
    name = raw["name"]
    if not isinstance(name, str) or not name or "/" in name:
        raise ConfigError("runs instance names must be non-empty text without a /")
    if unknown := sorted(raw.keys() - _INSTANCE_KEYS):
        raise ConfigError(
            f"runs instance {name}: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_INSTANCE_KEYS))}",
            [f"runs.{name}.{key}" for key in unknown],
        )
    kind, url = raw["type"], raw["url"]
    try:
        runs_adapter(kind)
    except ConfigError as exc:
        raise ConfigError(f"runs instance {name}: {exc}") from exc
    if not isinstance(url, str):
        raise ConfigError(f"runs instance {name}: url must be text")
    run_safe, domains = raw.get("run_safe", []), raw.get("domains", {})
    if not _names(run_safe):
        raise ConfigError(f"runs instance {name}: run_safe must be a list of workflow names")
    if not isinstance(domains, dict) or not all(_names(workflows) for workflows in domains.values()):
        raise ConfigError(f"runs instance {name}: domains must map each domain name to a list of workflow names")
    token_env = raw.get("token_env")
    if token_env is not None and not (isinstance(token_env, str) and _ENV_NAME.fullmatch(token_env)):
        raise ConfigError(f"runs instance {name}: token_env must be the name of an environment variable")
    return RunsInstance(
        name, kind, url, tuple(run_safe), {domain: tuple(ws) for domain, ws in domains.items()}, token_env
    )


@dataclass(frozen=True)
class Config:
    tracker_url: str | None
    """The tracker's web address; a task links to `<tracker_url>/tasks/<id>`, or with none to the page's own Kanban."""
    mode: str
    """`ic` for one person on one machine. A hub is started with `starpulse serve --hub`, not by this key."""
    runs: tuple[RunsInstance, ...] = ()
    harnesses: Harnesses | None = None
    """The tiers and per-harness models `harnesses_file` declares; none when the config names no file."""
    board_type: str = DEFAULT_TYPE
    """The board adapter module: a name under `starpulse`, or a dotted module path."""
    board: Mapping[str, object] = field(default_factory=dict)
    """The `[board]` table, the adapter's settings."""
    database_url: str | None = None
    """The history store's SQLAlchemy URL; None keeps it in a SQLite file beside the config."""
    session_start_url: str | None = None
    """The session-start service a started task is sent to (`POST <url>/start/TASK-N`); none: nothing can be started."""

    def qualified_domains(self) -> dict[str, tuple[str, ...]]:
        """Every instance's domains as `<instance>/<workflow>`, one entry per domain name, in first-seen order."""
        merged: dict[str, tuple[str, ...]] = {}
        for instance in self.runs:
            for domain, workflows in instance.domains.items():
                merged[domain] = (*merged.get(domain, ()), *(f"{instance.name}/{w}" for w in workflows))
        return merged

    def qualified_run_safe(self) -> tuple[str, ...]:
        """Every instance's run-safe workflows as `<instance>/<workflow>`."""
        return tuple(f"{instance.name}/{w}" for instance in self.runs for w in instance.run_safe)


def discover(path: Path | None) -> Path | None:
    """`path`, else `starpulse.toml` in the working directory when it exists, else None (the defaults)."""
    if path is None and Path("starpulse.toml").is_file():
        return Path("starpulse.toml")
    return path


def load(path: Path | None) -> Config:
    """The config in `path`, or the defaults when there is none."""
    raw = tomllib.loads(path.read_text()) if path else {}
    if unknown := sorted(raw.keys() - _KEYS):
        raise ConfigError(f"unknown config key(s) {', '.join(unknown)}; known: {', '.join(sorted(_KEYS))}", unknown)
    if (mode := raw.get("mode", "ic")) != "ic":
        raise ConfigError(f'mode {mode!r} is not a config setting; use mode = "ic", and start a hub with `serve --hub`')
    runs_raw = raw.get("runs", [])
    if not isinstance(runs_raw, list):
        raise ConfigError("runs must be a list of [[runs]] tables")
    runs = tuple(_instance(table) for table in runs_raw)
    for at, instance in enumerate(runs):
        if any(instance.name == earlier.name for earlier in runs[:at]):
            raise ConfigError(f"runs instance {instance.name} is configured twice")
        if instance.token_env and (shared := next((e for e in runs[:at] if e.token_env == instance.token_env), None)):
            raise ConfigError(
                f"runs instances {shared.name} and {instance.name} share token_env {instance.token_env}; "
                "each needs its own token"
            )
    if not isinstance(session_start_url := raw.get("session_start_url"), str | None):
        raise ConfigError("session_start_url must be text")
    harnesses = None
    if path and (name := raw.get("harnesses_file")):
        if not (file := path.parent / name).is_file():
            raise ConfigError(f"harnesses_file {file} does not exist")
        harnesses = load_harnesses(file)
    board = raw.get("board", {})
    if not isinstance(board, dict):
        raise ConfigError("board must be a [board] table")
    kind = board.get("type", DEFAULT_TYPE)
    if not isinstance(kind, str) or not all(part.isidentifier() for part in kind.split(".")):
        raise ConfigError(f"board type {kind!r} is not a module name")
    try:
        found = importlib.util.find_spec(module_name(kind))
    except ModuleNotFoundError:
        found = None
    if found is None:
        raise ConfigError(f"no board adapter of type {kind}")
    url = raw.get("database_url")
    if url is not None and not isinstance(url, str):
        raise ConfigError("database_url must be text")
    return Config(raw.get("tracker_url"), mode, runs, harnesses, kind, board, url, session_start_url)
