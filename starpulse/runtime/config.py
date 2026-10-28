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
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import ModuleType

from starpulse.board.model.adapter_types import DEFAULT_TYPE, module_name
from starpulse.board.model.commit_keys import CommitKeys
from starpulse.board.model.search_config import Search, SearchError, parse_search
from starpulse.cli.project import Project, ProjectError, parse_project
from starpulse.contracts.analytics import Analytics, AnalyticsError, parse_analytics
from starpulse.flow_metrics.model.level import Level, LevelError, parse_level
from starpulse.harness_telemetry.cursor_context_config import (
    CursorContext,
    CursorContextError,
    parse_cursor_context,
)
from starpulse.harness_telemetry.harnesses import Harnesses, load_harnesses
from starpulse.pulls.pins import Repo
from starpulse.runs.config import Producer, RunsInstance
from starpulse.runtime.config_model import (
    WORKER_MEMORY_MB,
    CommitFile,
    ConfigFile,
    MemoryFile,
    ProducerFile,
    RepoFile,
    RunsInstanceFile,
)
from starpulse.scheduler.model.config import Scheduler, SchedulerError, parse_scheduler

_DEFAULTS = ConfigFile()
_KEYS = set(ConfigFile.model_fields)
_INSTANCE_KEYS = set(RunsInstanceFile.model_fields)
_COMMIT_KEYS = set(CommitFile.model_fields)
_REPO_KEYS = set(RepoFile.model_fields)
_PRODUCER_KEYS = set(ProducerFile.model_fields)
_MEMORY_KEYS = set(MemoryFile.model_fields)

_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

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


def _names(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(name, str) for name in value)


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
    kind, url = raw.get("type"), raw.get("url")
    try:
        runs_adapter(kind)
    except ConfigError as exc:
        raise ConfigError(f"runs instance {name}: {exc}") from exc
    if not isinstance(url, str):
        raise ConfigError(f"runs instance {name}: url must be text")
    run_safe, domains = raw.get("run_safe", []), raw.get("domains", {})
    if not _names(run_safe):
        raise ConfigError(f"runs instance {name}: run_safe must be a list of workflow names")
    flat, processes = _domains(domains, name)
    return RunsInstance(
        name,
        kind,
        url,
        tuple(run_safe),
        flat,
        processes,
        _commit(raw["commit"], name) if "commit" in raw else None,
    )


def _domains(
    raw: object, name: str
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[tuple[str, tuple[str, ...]], ...]]]:
    """A runs instance's `domains`: each domain is a workflow list, or a table of process name to workflow list."""
    refusal = f"runs instance {name}: domains must map each domain name to a list of workflow names"
    if not isinstance(raw, dict):
        raise ConfigError(refusal)
    domains: dict[str, tuple[str, ...]] = {}
    processes: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {}
    for domain, value in raw.items():
        if _names(value):
            domains[domain] = tuple(value)
            processes[domain] = ()
        elif isinstance(value, dict) and all(_names(ws) for ws in value.values()):
            ordered = tuple((proc, tuple(ws)) for proc, ws in value.items())
            workflows = [w for _, ws in ordered for w in ws]
            for w in workflows:
                if workflows.count(w) > 1:
                    raise ConfigError(
                        f"runs instance {name}: workflow {w!r} listed twice (duplicate) in the processes under {domain!r}"
                    )
            domains[domain] = tuple(sorted(workflows))
            processes[domain] = ordered
        else:
            raise ConfigError(refusal)
    return domains, processes


def _commit(raw: object, instance: str) -> CommitKeys:
    """The `[runs.commit]` table as keys; each refusal names the key to fix."""
    who = f"runs instance {instance}"
    if not isinstance(raw, dict):
        raise ConfigError(f"{who}: commit must be a [runs.commit] table")
    if unknown := sorted(raw.keys() - _COMMIT_KEYS):
        raise ConfigError(
            f"{who}: commit: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_COMMIT_KEYS))}"
        )
    for key, name in raw.items():
        if not (isinstance(name, str) and _ENV_NAME.fullmatch(name)):
            raise ConfigError(f"{who}: commit.{key} must be the name of a run parameter")
    return CommitKeys(**raw)


def _repo(raw: object) -> Repo:
    """One `[[repos]]` table as a repository; each refusal names the key to fix."""
    if not isinstance(raw, dict):
        raise ConfigError("repos must be a list of [[repos]] tables")
    for key in ("name", "path", "applied_by"):
        if key not in raw:
            raise ConfigError(f"a repos entry needs {key}")
    name, path, applied_by = raw["name"], raw["path"], raw["applied_by"]
    if not isinstance(name, str) or not name or "/" in name:
        raise ConfigError("repos names must be non-empty text without a /")
    _unknown(raw, _REPO_KEYS, f"repos entry {name}")
    if not isinstance(path, str) or not path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
        raise ConfigError(f"repos entry {name}: path must be a relative path inside the parent repository")
    if applied_by != "pin-bump":
        raise ConfigError(f"repos entry {name}: applied_by must be pin-bump")
    return Repo(name, path, applied_by)


def _repos(raw: object) -> tuple[Repo, ...]:
    if not isinstance(raw, list):
        raise ConfigError("repos must be a list of [[repos]] tables")
    repos = tuple(_repo(table) for table in raw)
    for at, repo in enumerate(repos):
        if any(repo.name == earlier.name for earlier in repos[:at]):
            raise ConfigError(f"repos entry {repo.name} is configured twice")
    return repos


def _refresh_token_env(raw: object) -> str | None:
    if raw is not None and not (isinstance(raw, str) and _ENV_NAME.fullmatch(raw)):
        raise ConfigError("refresh_token_env must be the name of an environment variable")
    return raw


def _take_over_command(raw: object) -> tuple[str, ...] | None:
    if raw is None:
        return None
    if not (isinstance(raw, list) and raw and all(isinstance(part, str) and part for part in raw)):
        raise ConfigError("take_over_command must be a non-empty list of strings")
    return tuple(raw)


def _token_env(raw: object, who: str) -> str:
    if not (isinstance(raw, str) and _ENV_NAME.fullmatch(raw)):
        raise ConfigError(f"{who} token_env must be the name of an environment variable")
    return raw


def _unknown(raw: dict, known: set[str], who: str) -> None:
    if unknown := sorted(raw.keys() - known):
        raise ConfigError(f"{who}: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(known))}")


def _name_list(raw: dict, key: str, who: str) -> tuple[str, ...]:
    names = raw[key]
    if not (isinstance(names, list) and names and all(isinstance(name, str) and name for name in names)):
        raise ConfigError(f"{who}: {key} must be a non-empty list of text")
    return tuple(names)


def _producer(raw: object) -> Producer:
    if not isinstance(raw, dict):
        raise ConfigError("producers must be a list of [[producers]] tables")
    for key in ("name", "token_env"):
        if key not in raw:
            raise ConfigError(f"a producer needs {key}")
    name = raw["name"]
    if not isinstance(name, str) or not name or "/" in name:
        raise ConfigError("producer names must be non-empty text without a /")
    who = f"producer {name}"
    _unknown(raw, _PRODUCER_KEYS, who)
    machines = _name_list(raw, "machines", who) if "machines" in raw else ()
    actors = _name_list(raw, "actors", who) if "actors" in raw else ()
    adapter = raw.get("adapter")
    if adapter is not None and not (isinstance(adapter, str) and adapter):
        raise ConfigError(f"{who}: adapter must be the name of a run adapter type")
    return Producer(name, _token_env(raw["token_env"], f"{who}:"), machines, actors, adapter)


def _producers(raw: object) -> tuple[Producer, ...]:
    if not isinstance(raw, list):
        raise ConfigError("producers must be a list of [[producers]] tables")
    producers = tuple(_producer(table) for table in raw)
    for at, producer in enumerate(producers):
        if any(producer.name == earlier.name for earlier in producers[:at]):
            raise ConfigError(f"producer {producer.name} is configured twice")
        if shared := next((p for p in producers[:at] if p.token_env == producer.token_env), None):
            raise ConfigError(
                f"producers {shared.name} and {producer.name} share token_env {producer.token_env}; each needs its own token"
            )
    return producers


@dataclass(frozen=True)
class MemoryLimit:
    """A worker child's memory limits in megabytes: past `soft_mb` it is replaced, past `hard_mb` it is killed."""

    soft_mb: int
    hard_mb: int


#: The limit of each `starpulse worker` context when `worker_memory` does not name one.
WORKER_MEMORY = {context: MemoryLimit(soft, hard) for context, (soft, hard) in WORKER_MEMORY_MB.items()}


def _megabytes(value: object, where: str, key: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{where}: {key} must be a whole number of megabytes, 1 or more")
    return value


def _worker_memory(raw: object) -> dict[str, MemoryLimit]:
    """The packaged limits with each `[worker_memory.<context>]` key laid over them."""
    if not isinstance(raw, dict) or not all(isinstance(v, dict) for v in raw.values()):
        raise ConfigError("worker_memory must be a table of per-context tables")
    if unknown := sorted(raw.keys() - WORKER_MEMORY.keys()):
        known = ", ".join(sorted(WORKER_MEMORY))
        raise ConfigError(f"worker_memory: unknown context(s) {', '.join(unknown)}; known: {known}")
    limits = dict(WORKER_MEMORY)
    for context, table in raw.items():
        where = f"worker_memory.{context}"
        if unknown := sorted(table.keys() - _MEMORY_KEYS):
            raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_MEMORY_KEYS))}")
        soft = _megabytes(table.get("soft_mb", limits[context].soft_mb), where, "soft_mb")
        hard = _megabytes(table.get("hard_mb", limits[context].hard_mb), where, "hard_mb")
        if soft >= hard:
            raise ConfigError(f"{where}: soft_mb must be below hard_mb")
        limits[context] = MemoryLimit(soft, hard)
    return limits


def _flag(raw: dict, key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be true or false")
    return value


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
    """The Loki base URL the harness adapters push telemetry signals to and the analytics views read; unset, the signals go to the event log."""
    repos: tuple[Repo, ...] = ()
    """The repositories whose merges apply through the parent's pin bump (`[[repos]]`)."""
    ci: tuple[str, ...] = ()
    """The Board states the shipped `ci` machine is attached to as a submachine (`[ci] states`); none: it is not drawn."""
    scheduler: Scheduler = field(default_factory=Scheduler)
    """The policy the scheduler runs under (`[scheduler]`); every key is optional, so no block is the defaults."""
    refresh_token_env: str | None = None
    """The environment variable holding the token `POST /api/pulls/refresh` accepts; none: the route answers 404."""
    take_over_command: tuple[str, ...] | None = None
    """The argv `POST /api/take-over` runs with the task id appended (exit 0 sent, 1 no workflow); none: the route answers 404."""
    pull_requests: bool = _DEFAULTS.pull_requests
    """`serve` keeps the pull request store, current from the lifecycle events (GitHub is read only for a pull request a refresh asks for); false: no store is kept, so an instance beside another that reads the same repositories keeps no second copy."""
    runs_worker: bool = _DEFAULTS.runs_worker
    """The Runs context (the run adapters and the pushed-runs follower) runs in `starpulse worker runs`, not in `serve`: `serve` starts none of them and draws the workflows the worker keeps in the event log; false: `serve` supervises that worker as a child."""
    worker_memory: Mapping[str, MemoryLimit] = field(default_factory=lambda: dict(WORKER_MEMORY))
    """The memory limits `serve` holds each worker child to: past `soft_mb` it replaces the child (starts a new one, then stops the old), past `hard_mb` it kills and restarts it. Keyed by context, `pulls`, `scheduler`, `runs`, `history` and `search`."""
    tls: tuple[Path, Path] | None = None
    """The certificate and key `tls_cert` and `tls_key` name: `serve` answers TLS, and HTTP/3 beside it; none is cleartext."""
    slow_read_seconds: float = _DEFAULTS.slow_read_seconds
    """`serve` logs a `slow_read` line for each `GET /api/pulls` that took this many seconds or more, from accept to the last byte written, with the seconds it waited for a handler thread, computed its answer and wrote it."""
    flow_metrics_worker: bool = _DEFAULTS.flow_metrics_worker
    """The Flow Metrics context (the recorder that copies the event log's machine events into the history store, and the hourly prune of the log) runs in `starpulse worker flow-metrics`, not in `serve`: `serve` starts neither thread; false: `serve` supervises that worker as a child."""
    search_worker: bool = _DEFAULTS.search_worker
    """The Search context's embedding catch-up (the thread that fills vectors for indexed task text) runs in `starpulse worker search`, not in `serve`: `serve` starts no thread; false: `serve` supervises that worker as a child when `[search]` names an `embeddings_url`."""
    board_worker: bool = _DEFAULTS.board_worker
    """The Board context's writer (the Start Criteria evaluation) runs in `starpulse worker board`, not in `serve`: `serve` starts no thread for it and reads the criteria results from the history store; false: `serve` supervises that worker as a child."""
    api_worker: bool = _DEFAULTS.api_worker
    """The Page API (the HTTP server for the page, its JSON and its event stream) runs in `starpulse worker api`, not in a child of `serve`: `serve` binds no socket and starts no API child; false: `serve` binds the listening socket, hands it to a `starpulse worker api` child it supervises and replaces that child behind the socket on a reload."""
    analytics: Analytics = field(default_factory=Analytics)
    """What the instance's agents' telemetry is read against (`[analytics]`); no table: no roots or stops."""
    release: Release | None = None
    """The `[release]` table: None releases no task, so a config without it leaves release to whoever does it today."""
    task_actor: bool = False
    """The `[board.actor]` table is present: `serve` runs the task actor, which moves a task on the facts its lane waits on and replaces the release pass."""
    search: Search = field(default_factory=Search)
    """The optional embeddings service that ranks search by meaning (`[search]`); no table: search is lexical only."""
    project: Project = field(default_factory=Project)
    """The project's own command line for each step a shipped skill names (`[project.commands]`); no table: none is mapped."""
    cursor_context: CursorContext = field(default_factory=CursorContext)
    """The context limit a Cursor task session is reset at (`[cursor_context]`); no table: 150000 of a 200000 window."""

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


def _release(raw: Mapping[str, object], repos: Sequence[Repo]) -> Release | None:
    """The `[release]` table, or None when the config has none; a table the server cannot apply is a `ConfigError`."""
    if "release" not in raw:
        return None
    table = raw["release"]
    if not isinstance(table, dict) or not table.keys() <= {"settle", "repo"}:
        raise ConfigError("release: the [release] table takes only settle and repo")
    settle, repo = table.get("settle"), table.get("repo")
    if repo is not None and settle != "release":
        raise ConfigError("release: repo is only for settle = release")
    if settle is None:
        return Release()
    if settle not in ("pin-bump", "release"):
        raise ConfigError("release: settle must be pin-bump or release")
    if settle == "release":
        if not isinstance(repo, str) or not repo:
            raise ConfigError("release: settle = release needs a repo, the repository the running build comes from")
        return Release(settle="release", repo=repo)
    if not repos:
        raise ConfigError(
            "release: settle = pin-bump needs a [[repos]] entry to say which repositories the parent pins"
        )
    return Release(settle="pin-bump")


def _level(raw: Mapping[str, object]) -> Level | None:
    """The `[level]` table's level, or None when the config has none; a table the schema refuses is a `ConfigError`."""
    try:
        return parse_level(raw["level"]) if "level" in raw else None
    except LevelError as exc:
        raise ConfigError(str(exc)) from exc


def _ci(raw: Mapping[str, object]) -> tuple[str, ...]:
    """The Board states the `[ci]` table names, or none when the config has no such table."""
    if "ci" not in raw:
        return ()
    table = raw["ci"]
    if not isinstance(table, dict) or table.keys() != {"states"}:
        raise ConfigError("ci: the [ci] table takes one key, states")
    states = table["states"]
    if not isinstance(states, list) or not states or not all(isinstance(s, str) and s for s in states):
        raise ConfigError("ci: states must be a non-empty list of Board state ids")
    return tuple(states)


def discover(path: Path | None) -> Path | None:
    """`path`, else `starpulse.toml` in the working directory when it exists, else None (the defaults). A linked
    `starpulse.toml` resolves to its target, so the files the config names are read from beside the target."""
    if path is None and Path("starpulse.toml").is_file():
        return Path("starpulse.toml").resolve()
    return path


def _retention(value: object, key: str) -> int:
    """The days `key` keeps rows for; a whole number, 1 or more."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{key} must be a whole number of days, 1 or more")
    return value


def _tls(raw: dict, path: Path | None) -> tuple[Path, Path] | None:
    """The certificate and key `raw` names, from beside the config file; both or neither, each a file that exists."""
    names = [raw.get("tls_cert"), raw.get("tls_key")]
    if names == [None, None]:
        return None
    if None in names or path is None:
        raise ConfigError("tls_cert and tls_key are set together")
    files = []
    for key, name in zip(("tls_cert", "tls_key"), names, strict=True):
        if not isinstance(name, str):
            raise ConfigError(f"{key} must be text")
        if not (file := path.parent / name).is_file():
            raise ConfigError(f"{key} {file} does not exist")
        files.append(file)
    return files[0], files[1]


def _slow_read(value: object) -> float:
    """The seconds a read takes to be logged as slow; a number above zero."""
    if not isinstance(value, int | float) or isinstance(value, bool) or not value > 0:
        raise ConfigError("slow_read_seconds must be a number of seconds above 0")
    return float(value)


def _archive_dir(value: object) -> str:
    """The directory `event_log_archive_dir` names; text, not empty."""
    if not isinstance(value, str) or not value:
        raise ConfigError("event_log_archive_dir must be a directory path")
    return value


def load(path: Path | None) -> Config:
    """The config in `path`, or the defaults when there is none."""
    raw = tomllib.loads(path.read_text()) if path else {}
    _check_keys(raw)
    mode = _mode(raw)
    runs = _runs(raw)
    session_start_url = _text(raw, "session_start_url")
    log_retention = _retention(
        raw.get("event_log_retention_days", _DEFAULTS.event_log_retention_days), "event_log_retention_days"
    )
    harnesses = _harnesses(raw, path)
    tls = _tls(raw, path)
    kind, board, task_actor = _board(raw)
    url = _text(raw, "database_url")
    repos = _repos(raw.get("repos", []))
    return _config(
        raw, mode, runs, harnesses, kind, board, url, session_start_url, log_retention, tls, task_actor, repos
    )


def _check_keys(raw: dict) -> None:
    if "triggers" in raw:
        raise ConfigError("[[triggers]] removed in 0.4: start runs from your orchestrator", ["triggers"])
    if unknown := sorted(raw.keys() - _KEYS):
        raise ConfigError(f"unknown config key(s) {', '.join(unknown)}; known: {', '.join(sorted(_KEYS))}", unknown)


def _mode(raw: dict) -> str:
    if (mode := raw.get("mode", "ic")) != "ic":
        raise ConfigError(f'mode {mode!r} is not a config setting; use mode = "ic"')
    return mode


def _runs(raw: dict) -> tuple[RunsInstance, ...]:
    runs_raw = raw.get("runs", [])
    if not isinstance(runs_raw, list):
        raise ConfigError("runs must be a list of [[runs]] tables")
    runs = tuple(_instance(table) for table in runs_raw)
    for at, instance in enumerate(runs):
        if any(instance.name == earlier.name for earlier in runs[:at]):
            raise ConfigError(f"runs instance {instance.name} is configured twice")
    return runs


def _text(raw: dict, key: str) -> str | None:
    if not isinstance(value := raw.get(key), str | None):
        raise ConfigError(f"{key} must be text")
    return value


def _harnesses(raw: dict, path: Path | None) -> Harnesses | None:
    if path and (name := raw.get("harnesses_file")):
        if not (file := path.parent / name).is_file():
            raise ConfigError(f"harnesses_file {file} does not exist")
        return load_harnesses(file)
    return None


def _board(raw: dict) -> tuple[str, dict, bool]:
    """The board adapter's type, its table without `[board.actor]`, and whether `[board.actor]` is present."""
    board = raw.get("board", {})
    if not isinstance(board, dict):
        raise ConfigError("board must be a [board] table")
    actor = board.get("actor")
    if "actor" in board:
        if not isinstance(actor, dict):
            raise ConfigError("board.actor must be a [board.actor] table")
        if actor:
            raise ConfigError("board.actor: the [board.actor] table takes no keys")
        board = {key: value for key, value in board.items() if key != "actor"}
    kind = board.get("type", DEFAULT_TYPE)
    if not isinstance(kind, str) or not all(part.isidentifier() for part in kind.split(".")):
        raise ConfigError(f"board type {kind!r} is not a module name")
    try:
        found = importlib.util.find_spec(module_name(kind))
    except ModuleNotFoundError, ValueError:
        found = None
    if found is None:
        raise ConfigError(f"no board adapter of type {kind}")
    return kind, board, actor is not None


def _config(
    raw: dict,
    mode: str,
    runs: tuple[RunsInstance, ...],
    harnesses: Harnesses | None,
    kind: str,
    board: dict,
    url: str | None,
    session_start_url: str | None,
    log_retention: int,
    tls: tuple[Path, Path] | None,
    task_actor: bool,
    repos: tuple[Repo, ...],
) -> Config:
    """The `Config` of the validated parts of `raw`, with the rest read from it as it is."""
    return Config(
        raw.get("tracker_url"),
        mode,
        runs,
        harnesses,
        kind,
        board,
        url,
        session_start_url,
        _level(raw),
        producers=_producers(raw.get("producers", [])),
        event_log_retention_days=log_retention,
        event_log_archive_dir=_archive_dir(raw.get("event_log_archive_dir", _DEFAULTS.event_log_archive_dir)),
        telemetry_loki_url=_text(raw, "telemetry_loki_url"),
        repos=repos,
        ci=_ci(raw),
        scheduler=_scheduler(raw.get("scheduler")),
        analytics=_analytics(raw.get("analytics")),
        release=_release(raw, repos),
        task_actor=task_actor,
        search=_search(raw.get("search")),
        project=_project(raw.get("project")),
        cursor_context=_cursor_context(raw.get("cursor_context")),
        refresh_token_env=_refresh_token_env(raw.get("refresh_token_env")),
        take_over_command=_take_over_command(raw.get("take_over_command")),
        pull_requests=_flag(raw, "pull_requests", _DEFAULTS.pull_requests),
        runs_worker=_flag(raw, "runs_worker", _DEFAULTS.runs_worker),
        worker_memory=_worker_memory(raw.get("worker_memory", {})),
        flow_metrics_worker=_flag(raw, "flow_metrics_worker", _DEFAULTS.flow_metrics_worker),
        search_worker=_flag(raw, "search_worker", _DEFAULTS.search_worker),
        board_worker=_flag(raw, "board_worker", _DEFAULTS.board_worker),
        api_worker=_flag(raw, "api_worker", _DEFAULTS.api_worker),
        slow_read_seconds=_slow_read(raw.get("slow_read_seconds", _DEFAULTS.slow_read_seconds)),
        tls=tls,
    )
