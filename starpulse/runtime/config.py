"""StarPulse's one config file: its board adapter, its history database, and which runs adapters run.

Database credentials never live here; they come from the driver's environment, such as `PGPASSWORD`.
With no file the view runs as an individual-contributor view of its own
Markdown board in `./.starpulse/board`, keeping its history in a SQLite file, with no runs adapter.

The `[board]` table names the board adapter by `type` (`starpulse.board`); the rest of the table is that
adapter's settings. `database_url` is the SQLAlchemy URL of the history store (`starpulse.flow_metrics.adapters.outbound.history`).

Each `[[runs]]` table is one instance of a runs adapter: its `name`, the adapter module `type` (a built-in name from
`board.model.adapter_types`, or the dotted path of a module an installed package provides), the `url` it reads, the workflows Run now may start (`run_safe`) and the `domains` that
group its workflows on the page. A workflow is shown as `<instance>/<workflow>`, so two instances can
carry the same workflow name.

The optional `[level]` table configures the flow graph drawn above the Board (`starpulse.flow_metrics.model.level`).
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic import ValidationError

from starpulse.board.model.adapter_types import DEFAULT_TYPE, module_name
from starpulse.board.model.commit_keys import CommitKeys
from starpulse.board.model.policy import refuse_retired
from starpulse.board.model.search_config import Search, SearchError, parse_search
from starpulse.bridge.subscriptions import parse_rules
from starpulse.cli.project import Project, ProjectError, parse_project
from starpulse.contracts.analytics import Analytics, AnalyticsError, parse_analytics
from starpulse.flow_metrics.model.level import Level, LevelError, parse_level
from starpulse.github.model.github_config import GitHub, GitHubConfigError, parse_github
from starpulse.harness_telemetry.model.claude_code_config import ClaudeCode, ClaudeCodeError, parse_claude_code
from starpulse.harness_telemetry.model.cursor_context_config import (
    CursorContext,
    CursorContextError,
    parse_cursor_context,
)
from starpulse.harness_telemetry.model.harnesses import Harnesses, load_harnesses
from starpulse.pulls.model.pins import Repo
from starpulse.runs.model.config import Producer, RunsInstance
from starpulse.runtime.config_model import (
    WORKER_MEMORY_MB,
    ConfigFile,
    ProducerFile,
    RepoFile,
    RunsInstanceFile,
    memory_limit,
)
from starpulse.scheduler.model.config import Scheduler, SchedulerError, parse_scheduler
from starpulse.runtime.nats_server import Bridge
from starpulse.sweeper.config import Sweeper, SweeperError, parse_sweeper

_DEFAULTS = ConfigFile()
_KEYS = set(ConfigFile.model_fields)

__all__ = [
    "Config",
    "ConfigError",
    "MemoryLimit",
    "load",
    "runs_adapter",
]


class ConfigError(ValueError):
    """The config file is not one the view can run from; `unknown_keys` names the keys it refused as unknown."""

    def __init__(self, message: str, unknown_keys: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.unknown_keys = tuple(unknown_keys)


@dataclass(frozen=True)
class Release:
    """The `[release]` table: StarPulse moves a Waiting task to Ready once its dependencies settle."""

    settle: str | None = None
    """`pin-bump` holds a dependency whose pull request is in a `[[repos]]` repository until the parent's pin bump applies
    it; `release` holds one whose pull request is in `repo` until the running build contains its merge commit; none: a
    dependency settles when its task is Done."""
    repo: str | None = None
    """The name of the repository the running build comes from, for `settle = "release"`."""


def runs_adapter(kind: str) -> ModuleType:
    """The runs adapter module `kind` names, which offers `start(url)` and `follow(url, runs, log)`, and optionally `rerun(url)`, `declared_params(url, workflow)` and `domains(url)`."""
    if not isinstance(kind, str) or not all(part.isidentifier() for part in kind.split(".")):
        raise ConfigError(f"no runs adapter of type {kind}")
    try:
        target = module_name(kind)
        module = importlib.import_module(target)
    except ValueError as exc:
        raise ConfigError(f"no runs adapter of type {kind}") from exc
    except ModuleNotFoundError as exc:
        if exc.name and (target == exc.name or target.startswith(f"{exc.name}.")):
            raise ConfigError(f"no runs adapter of type {kind}") from exc
        raise ConfigError(f"runs adapter {kind} failed to import: {exc}") from exc
    except ImportError as exc:
        raise ConfigError(f"runs adapter {kind} failed to import: {exc}") from exc
    if not (callable(getattr(module, "start", None)) and callable(getattr(module, "follow", None))):
        raise ConfigError(f"{kind} is not a runs adapter: it needs start(url) and follow(url, runs, log)")
    return module


def _instance(table: RunsInstanceFile) -> RunsInstance:
    try:
        runs_adapter(table.type)
    except ConfigError as exc:
        raise ConfigError(f"runs instance {table.name}: {exc}") from exc
    flat, processes = _domains(table.domains)
    commit = CommitKeys(**table.commit.model_dump()) if table.commit is not None else None
    return RunsInstance(table.name, table.type, table.url, tuple(table.run_safe), flat, processes, commit)


def _domains(
    raw: dict[str, list[str] | dict[str, list[str]]],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[tuple[str, tuple[str, ...]], ...]]]:
    """A runs instance's `domains`: each domain is a workflow list, or a table of process name to workflow list."""
    domains: dict[str, tuple[str, ...]] = {}
    processes: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {}
    for domain, value in raw.items():
        if isinstance(value, dict):
            ordered = tuple((proc, tuple(ws)) for proc, ws in value.items())
            domains[domain] = tuple(sorted(w for _, ws in ordered for w in ws))
            processes[domain] = ordered
        else:
            domains[domain] = tuple(value)
            processes[domain] = ()
    return domains, processes


def _repos(tables: list[RepoFile]) -> tuple[Repo, ...]:
    return tuple(Repo(table.name, table.path, table.applied_by) for table in tables)


def _producers(tables: list[ProducerFile]) -> tuple[Producer, ...]:
    return tuple(
        Producer(table.name, table.token_env, tuple(table.machines), tuple(table.actors), table.adapter)
        for table in tables
    )


@dataclass(frozen=True)
class MemoryLimit:
    """A worker child's memory limits in megabytes: past `soft_mb` it is replaced, past `hard_mb` it is killed."""

    soft_mb: int
    hard_mb: int


#: The limit of each child `serve` supervises when `worker_memory` does not name one.
WORKER_MEMORY = {context: MemoryLimit(soft, hard) for context, (soft, hard) in WORKER_MEMORY_MB.items()}


def _worker_memory(file: ConfigFile) -> dict[str, MemoryLimit]:
    """The packaged limits with each `[worker_memory.api]` and `[worker_memory.contexts]` key laid over them."""
    return {**WORKER_MEMORY, **{c: MemoryLimit(*memory_limit(c, t)) for c, t in file.worker_memory.items()}}


@dataclass(frozen=True)
class Config:
    tracker_url: str | None
    """The tracker's web address; a task links to `<tracker_url>/tasks/<id>`, or with none to the page's own Kanban."""
    mode: str
    """`ic`, the one value: one person on one machine."""
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
    """The session-start service a started task is sent to (`POST <url>/start/TASK-N?harness=&mode=`); none: nothing can be started."""
    level: Level | None = None
    """The `[level]` flow graph above the Board; none when the config has no such table."""
    producers: tuple[Producer, ...] = ()
    """The systems that post machine events as CloudEvents, each with its token variable, machines and actors."""
    event_log_retention_days: int = _DEFAULTS.event_log_retention_days
    """`serve` prunes the event log's rows older than this many days, hourly, so the table and every reader's boot replay stay bounded; a reader that was behind the oldest retained row records a gap."""
    event_log_archive_dir: str = _DEFAULTS.event_log_archive_dir
    """Where `serve` writes the event log rows it prunes, one gzip JSONL file per UTC day, before it deletes them; a relative path is beside the config."""
    telemetry_loki_url: str | None = None
    """The Loki base URL `copy-signals` reads the old signal stream from, to fill `starpulse_signals` at the cutover."""
    repos: tuple[Repo, ...] = ()
    """The repositories whose merges apply through the parent's pin bump (`[[repos]]`)."""
    ci: tuple[str, ...] = ()
    """The Board states the shipped `ci` machine is attached to as a submachine (`[ci] states`); none: it is not drawn."""
    scheduler: Scheduler = field(default_factory=Scheduler)
    """The policy the scheduler runs under (`[scheduler]`); every key is optional, so no block is the defaults."""
    refresh_token_env: str | None = None
    """The environment variable holding the token `POST /api/pulls/refresh` accepts; none: the route answers 404."""
    github_token_env: str | None = None
    """The environment variable whose value `serve` exports as `GITHUB_TOKEN` and `GH_TOKEN` before any worker starts; unset, both are left as they were."""
    take_over_command: tuple[str, ...] | None = None
    """The argv `POST /api/take-over` runs with the task id appended (exit 0 sent, 1 no workflow); none: the route answers 404."""
    pull_requests: bool = _DEFAULTS.pull_requests
    """`serve` keeps the pull request store, current from the lifecycle events (GitHub is read only for a pull request a refresh asks for); false: no store is kept, so an instance beside another that reads the same repositories keeps no second copy."""
    worker_memory: Mapping[str, MemoryLimit] = field(default_factory=lambda: dict(WORKER_MEMORY))
    """The memory limits `serve` holds each worker child to: past `soft_mb` it replaces the child (starts a new one, then stops the old), past `hard_mb` it kills and restarts it. Keyed by context, `pulls`, `scheduler`, `runs`, `history` and `search`."""
    tls: tuple[Path, Path] | None = None
    """The certificate and key `tls_cert` and `tls_key` name: `serve` answers TLS, and HTTP/3 beside it; none is cleartext."""
    host: str = _DEFAULTS.host
    """The address `serve` and `worker api` listen on when no `--host` is given."""
    port: int = _DEFAULTS.port
    """The port they listen on when no `--port` is given."""
    hours: float = _DEFAULTS.hours
    """How far back a task's latest move on a machine counts when no `--hours` is given."""
    slow_read_seconds: float = _DEFAULTS.slow_read_seconds
    """`serve` logs a `slow_read` line for each `GET /api/pulls` that took this many seconds or more, from accept to the last byte written, with the seconds it waited for a handler thread, computed its answer and wrote it."""
    analytics: Analytics = field(default_factory=Analytics)
    """What the instance's agents' telemetry is read against (`[analytics]`); no table: no roots or stops."""
    release: Release | None = None
    """The `[release]` table: None releases no task, so a config without it leaves release to whoever does it today."""
    task_actor: bool = False
    """The `[board.actor]` table is present: `serve` runs the task actor, which moves a task on the facts its lane waits on and replaces the release pass."""
    board_repo: str | None = None
    """`[board.actor] repo`, the `owner/name` the board's own pull requests live in: the actor renders them as a bare `PR #N`."""
    search: Search = field(default_factory=Search)
    """The optional embeddings service that ranks search by meaning (`[search]`); no table: search is lexical only."""
    sequences: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """The phases a task of each type goes through (`[sequences]`), with `default` for an unnamed type; no table: none."""
    project: Project = field(default_factory=Project)
    """The project's own command line for each step a shipped skill names (`[project.commands]`); no table: none is mapped."""
    cursor_context: CursorContext = field(default_factory=CursorContext)
    """The context limit a Cursor task session is reset at (`[cursor_context]`); no table: 150000 of a 200000 window."""
    claude_code: ClaudeCode | None = None
    """The Claude Code adapter the `contexts` child runs (`[claude_code]`); no table: none runs."""
    github: GitHub | None = None
    """The GitHub intake listener the `contexts` child runs (`[github]`); no table: none runs."""
    bridge: Bridge = field(default_factory=Bridge)
    """The NATS server `serve` supervises as its `nats` child (`[bridge]`); no table: none starts."""
    sweeper: Sweeper = field(default_factory=Sweeper)
    """The sweeper's pass interval and the kinds and housekeeping it runs as commands (`[sweeper]`); no table: an hourly pass."""

    def reads_domains_at_start(self) -> bool:
        """Whether an instance lists no domains and its adapter reads them from its workflows as `serve` starts."""
        return any(i.url and not i.domains and hasattr(runs_adapter(i.type), "domains") for i in self.runs)

    def qualified_domains(self) -> dict[str, tuple[str, ...]]:
        """Every instance's domains as `<instance>/<workflow>`, one entry per domain name, in first-seen order."""
        merged: dict[str, tuple[str, ...]] = {}
        for instance in self.runs:
            for domain, workflows in instance.domains.items():
                merged[domain] = (*merged.get(domain, ()), *(f"{instance.name}/{w}" for w in workflows))
        return merged

    def qualified_processes(self) -> dict[str, tuple[tuple[str, tuple[str, ...]], ...]]:
        """Every instance's processes with workflows as `<instance>/<workflow>`, per domain name, in first-seen order."""
        merged: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {}
        for instance in self.runs:
            for domain, packages in instance.processes.items():
                qualified = tuple((proc, tuple(f"{instance.name}/{w}" for w in ws)) for proc, ws in packages)
                merged[domain] = (*merged.get(domain, ()), *qualified)
        return merged

    def qualified_run_safe(self) -> tuple[str, ...]:
        """Every instance's run-safe workflows as `<instance>/<workflow>`."""
        return tuple(f"{instance.name}/{w}" for instance in self.runs for w in instance.run_safe)


def _scheduler(raw: object) -> Scheduler:
    """The `[scheduler]` table's policy, or the defaults when the config has none; a refusal is a `ConfigError`."""
    try:
        return parse_scheduler(raw)
    except SchedulerError as exc:
        raise ConfigError(str(exc)) from exc


def _analytics(raw: object) -> Analytics:
    """The `[analytics]` table, or the empty one when the config has none; a refusal is a `ConfigError`."""
    try:
        return parse_analytics(raw)
    except AnalyticsError as exc:
        raise ConfigError(str(exc)) from exc


def _sequences(raw: dict[str, list[str]] | None) -> dict[str, tuple[str, ...]]:
    return {kind: tuple(phases) for kind, phases in (raw or {}).items()}


def _project(raw: object) -> Project:
    """The `[project]` table, or the empty one when the config has none; a refusal is a `ConfigError`."""
    try:
        return parse_project(raw)
    except ProjectError as exc:
        raise ConfigError(str(exc)) from exc


def _search(raw: object) -> Search:
    """The `[search]` table, or the lexical-only one when the config has none; a refusal is a `ConfigError`."""
    try:
        return parse_search(raw)
    except SearchError as exc:
        raise ConfigError(str(exc)) from exc


def _cursor_context(raw: object) -> CursorContext:
    """The `[cursor_context]` table, or the default limit when the config has none; a refusal is a `ConfigError`."""
    try:
        return parse_cursor_context(raw)
    except CursorContextError as exc:
        raise ConfigError(str(exc)) from exc


def _claude_code(raw: object) -> ClaudeCode | None:
    """The `[claude_code]` table, or None when the config has none; a refusal is a `ConfigError`."""
    try:
        return parse_claude_code(raw)
    except ClaudeCodeError as exc:
        raise ConfigError(str(exc)) from exc


def _github(raw: object) -> GitHub | None:
    """The `[github]` table, or None when the config has none; a refusal is a `ConfigError`."""
    try:
        return parse_github(raw)
    except GitHubConfigError as exc:
        raise ConfigError(str(exc)) from exc


def _sweeper(raw: object) -> Sweeper:
    """The `[sweeper]` table, or its defaults when the config has none; a refusal is a `ConfigError`."""
    try:
        return parse_sweeper(raw)  # type: ignore[arg-type]
    except SweeperError as exc:
        raise ConfigError(str(exc)) from exc


def _release(file: ConfigFile) -> Release | None:
    """The `[release]` table, or None when the config has none."""
    if file.release is None:
        return None
    return Release(file.release.settle, file.release.repo)


def _level(raw: dict[str, Any] | None) -> Level | None:
    """The `[level]` table's level, or None when the config has none; a table the schema refuses is a `ConfigError`."""
    if raw is None:
        return None
    try:
        return parse_level(raw)
    except LevelError as exc:
        raise ConfigError(str(exc)) from exc


def discover(path: Path | None) -> Path | None:
    """`path`, else `starpulse.toml` in the working directory when it exists, else None (the defaults). A linked
    `starpulse.toml` resolves to its target, so the files the config names are read from beside the target."""
    if path is None and Path("starpulse.toml").is_file():
        return Path("starpulse.toml").resolve()
    return path


def _tls(file: ConfigFile, path: Path | None) -> tuple[Path, Path] | None:
    """The certificate and key `tls_cert` and `tls_key` name, from beside the config file; the model holds them to both or
    neither. Whether they exist is `serve`'s to check: a client reads the same config and never opens them, and a release
    can name them before the host issues them."""
    if path is None or file.tls_cert is None or file.tls_key is None:
        return None
    return path.parent / file.tls_cert, path.parent / file.tls_key


def _dotted(loc: Sequence[int | str]) -> str:
    """A pydantic error location in the config's own spelling: `runs[0].name`."""
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else part
    return out


def _refusal(exc: ValidationError) -> ConfigError:
    """The first violation as one line naming its key; every key it refused as unknown is listed beside it."""
    errors = exc.errors()
    where = _dotted(errors[0]["loc"])
    text = errors[0]["msg"].removeprefix("Value error, ")
    unknown = [_dotted(error["loc"]) for error in errors if error["type"] == "extra_forbidden"]
    return ConfigError(f"{where}: {text}" if where else text, unknown)


def _harnesses(file: ConfigFile, path: Path | None) -> Harnesses | None:
    if path and file.harnesses_file:
        if not (found := path.parent / file.harnesses_file).is_file():
            raise ConfigError(f"harnesses_file {found} does not exist")
        return load_harnesses(found)
    return None


def _board(table: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The board adapter's type, and its table without `[board.actor]`; a type that names no adapter is a `ConfigError`."""
    board = {key: value for key, value in table.items() if key != "actor"}
    try:
        refuse_retired(board)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    kind = board.get("type", DEFAULT_TYPE)
    if not isinstance(kind, str) or not all(part.isidentifier() for part in kind.split(".")):
        raise ConfigError(f"board type {kind!r} is not a module name")
    try:
        found = importlib.util.find_spec(module_name(kind))
    except ModuleNotFoundError, ValueError:
        found = None
    if found is None:
        raise ConfigError(f"no board adapter of type {kind}")
    return kind, board


#: Set to `{"database_url", "archive_dir"}` as JSON by `starpulse rehearse`: every process it starts then loads the config
#: as `rehearsal` reshapes it.
REHEARSE_ENV = "STARPULSE_REHEARSE"

#: The keys that reach a service beyond the store or answer on a network address: a rehearsal drops each.
_OUTBOUND = (
    "tracker_url",
    "telemetry_loki_url",
    "tls_cert",
    "tls_key",
    "session_start_url",
    "refresh_token_env",
    "github_token_env",
    "take_over_command",
    "producers",
    "claude_code",
    "github",
    "search",
)


def rehearsing() -> bool:
    """Whether this process is a rehearsal's."""
    return REHEARSE_ENV in os.environ


def rehearsal(raw: dict[str, Any], spec: dict[str, str]) -> dict[str, Any]:
    """`raw` as a rehearsal loads it: the copy of the store in `spec`, its pruned rows archived in `spec`'s scratch
    directory, and TLS, telemetry, adapters, producers, pull requests and every outbound call off, and the claim sweep, which would release claims in the live board files. `repos` and `runs` stay: Board
    assembly checks the writers and the release against them; `contexts_of` starts no context that reads them out."""
    kept = {key: value for key, value in raw.items() if key not in _OUTBOUND}
    return {
        **kept,
        "board": {**raw.get("board", {}), "claim_ttl": 0},  # the board's files are the live ones: no claim sweep
        "pull_requests": False,
        "database_url": spec["database_url"],
        "event_log_archive_dir": spec["archive_dir"],
    }


def load(path: Path | None) -> Config:
    """The config in `path`, or the defaults when there is none; under `REHEARSE_ENV` as `rehearsal` reshapes it."""
    raw = tomllib.loads(path.read_text()) if path else {}
    if spec := os.environ.get(REHEARSE_ENV):
        raw = rehearsal(raw, json.loads(spec))
    if "triggers" in raw:
        raise ConfigError("[[triggers]] removed in 0.4: start runs from your orchestrator", ["triggers"])
    try:
        file = ConfigFile.model_validate(raw)
    except ValidationError as exc:
        raise _refusal(exc) from exc
    kind, board = _board(file.board)
    return Config(
        file.tracker_url,
        file.mode,
        tuple(_instance(table) for table in file.runs),
        _harnesses(file, path),
        kind,
        board,
        file.database_url,
        file.session_start_url,
        _level(file.level),
        producers=_producers(file.producers),
        event_log_retention_days=file.event_log_retention_days,
        event_log_archive_dir=file.event_log_archive_dir,
        telemetry_loki_url=file.telemetry_loki_url,
        repos=_repos(file.repos),
        ci=tuple(file.ci.states) if file.ci is not None else (),
        scheduler=_scheduler(file.scheduler),
        analytics=_analytics(file.analytics),
        release=_release(file),
        task_actor="actor" in file.board,
        board_repo=file.board.get("actor", {}).get("repo"),
        search=_search(file.search),
        sequences=_sequences(file.sequences),
        project=_project(file.project),
        cursor_context=_cursor_context(file.cursor_context),
        claude_code=_claude_code(file.claude_code),
        github=_github(file.github),
        bridge=Bridge(
            file.bridge.enabled,
            file.bridge.port,
            file.bridge.store_dir,
            file.bridge.board,
            parse_rules({kind: rules.model_dump() for kind, rules in file.bridge.subscriptions.items()}),
            tuple(file.bridge.resume),
        ),
        sweeper=_sweeper(file.sweeper),
        refresh_token_env=file.refresh_token_env,
        github_token_env=file.github_token_env,
        take_over_command=tuple(file.take_over_command) if file.take_over_command is not None else None,
        pull_requests=file.pull_requests,
        worker_memory=_worker_memory(file),
        slow_read_seconds=float(file.slow_read_seconds),
        tls=_tls(file, path),
        host=file.host,
        port=file.port,
        hours=float(file.hours),
    )
