"""StarPulse's one config file: its board adapter, its history database, and which runs adapters run.

Database credentials never live here; they come from the driver's environment, such as `PGPASSWORD`.
With no file the view runs as an individual-contributor view of its own
Markdown board in `./.starpulse/board`, keeping its history in a SQLite file, with no runs adapter.

The `[board]` table names the board adapter by `type` (`starpulse.board`); the rest of the table is that
adapter's settings. `database_url` is the SQLAlchemy URL of the history store (`starpulse.history`).

Each `[[runs]]` table is one instance of a runs adapter: its `name`, the adapter module `type` (a built-in name from
`config.adapter_types`, or the dotted path of a module an installed package provides), the `url` it reads (an instance with a
`token_env` and neither `type` nor `url` is push-only: it pulls nothing and draws what the ingest receives), the workflows Run now may start (`run_safe`) and the `domains` that
group its workflows on the page, and optionally `token_env`, the name of the environment variable that holds the
token the HTTP ingest accepts for it (the token itself is never in this file). A workflow is shown as `<instance>/<workflow>`, so two instances can
carry the same workflow name.

The optional `[level]` table configures the flow graph a hub draws above the Board (`starpulse._internal.config.level`).
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
from urllib.parse import urlsplit

from starpulse._internal.config.adapter_types import module_name
from starpulse._internal.config.autopilot import Autopilot, AutopilotError, parse_autopilot
from starpulse._internal.config.level import Level, LevelError, parse_level
from starpulse._internal.config.harnesses import Harnesses, load_harnesses
from starpulse._internal.config.analytics import Analytics, AnalyticsError, parse_analytics
from starpulse._internal.config.search import Search, SearchError, parse_search
from starpulse._internal.config.triggers import Trigger, TriggerError, parse_triggers

#: The board adapter type a config without a `[board]` table names.
DEFAULT_TYPE = "native"


_KEYS = {
    "tracker_url",
    "mode",
    "runs",
    "repos",
    "harnesses_file",
    "board",
    "database_url",
    "session_start_url",
    "level",
    "ci",
    "hub_retention_days",
    "event_log_retention_days",
    "event_log_archive_dir",
    "oidc",
    "forward",
    "sources",
    "aggregates_only",
    "autopilot",
    "release",
    "triggers",
    "analytics",
    "search",
}
_OIDC_KEYS = {
    "issuer",
    "client_id",
    "client_secret_env",
    "redirect_uri",
    "allowed_groups",
    "groups_claim",
    "scopes",
    "engine_token_env",
    "reader_token_env",
}
_INSTANCE_KEYS = {"name", "type", "url", "run_safe", "domains", "token_env", "commit"}
_COMMIT_KEYS = {"after", "before", "force", "task"}
_REPO_KEYS = {"name", "path", "applied_by"}
_FORWARD_KEYS = {"url", "token_env", "batch"}
_SOURCE_KEYS = {"name", "token_env"}

_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

__all__ = ["CommitKeys", "Config", "ConfigError", "Forward", "RunsInstance", "Source", "load", "runs_adapter"]


class ConfigError(ValueError):
    """The config file is not one the view can run from; `unknown_keys` names the keys it refused as unknown."""

    def __init__(self, message: str, unknown_keys: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.unknown_keys = tuple(unknown_keys)


def _names(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(name, str) for name in value)


@dataclass(frozen=True)
class CommitKeys:
    """The run parameters of one runs instance that carry a commit or a task: a key left out is a parameter the
    instance's workflows do not take."""

    after: str | None = None
    """The parameter naming the commit a run applies (the merge's SHA)."""
    before: str | None = None
    """The parameter naming the commit the run starts from."""
    force: str | None = None
    """The parameter that marks a forced rerun."""
    task: str | None = None
    """The parameter naming the task a run was started for, which pairs a run with a non-merge Board transition."""


@dataclass(frozen=True)
class RunsInstance:
    """One configured runs adapter: the workflows it lists are shown as `<name>/<workflow>`."""

    name: str
    type: str | None
    """The adapter module that reads the instance: a name under `starpulse`, or a dotted module path; none: a push-only instance."""
    url: str | None
    """What the adapter reads; none with no type."""
    run_safe: tuple[str, ...] = ()
    """The workflows Run now may start; any other answers 404, so none is startable by default."""
    domains: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """The page's groups of this instance's workflows, in the order it lays them out."""
    token_env: str | None = None
    """The environment variable holding this instance's ingest token; none: the instance takes no pushed events."""
    commit: CommitKeys | None = None
    """The `[runs.commit]` table; none: a run pairs with a merge only by the time it started."""


@dataclass(frozen=True)
class Repo:
    """A repository whose merges reach live state through the parent's pin bump (`[[repos]]`)."""

    name: str
    """The repository's name as its pull request links spell it (`trantor-org/<name>`)."""
    path: str
    """Where the parent repository holds it as a submodule."""
    applied_by: str
    """How its merges are applied; only `pin-bump`."""


@dataclass(frozen=True)
class Release:
    """The `[release]` table: StarPulse moves a Waiting task to Ready once its dependencies settle."""

    settle: str | None = None
    """`pin-bump` holds a dependency whose pull request is in a `[[repos]]` repository until the parent's pin bump applies
    it; none: a dependency settles when its task is Done."""


@dataclass(frozen=True)
class OidcSettings:
    """The hub's sign-in: its OpenID Connect issuer, this hub's client at it, and who may sign in."""

    issuer: str
    client_id: str
    client_secret_env: str
    redirect_uri: str
    allowed_groups: tuple[str, ...]
    groups_claim: str = "groups"
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    engine_token_env: str | None = None
    reader_token_env: str | None = None


def _oidc(raw: object) -> OidcSettings:
    """The `[oidc]` table as settings; each refusal names the key to fix."""
    if not isinstance(raw, dict):
        raise ConfigError("oidc must be an [oidc] table")
    if unknown := sorted(raw.keys() - _OIDC_KEYS):
        raise ConfigError(f"oidc: unknown key(s) {', '.join(unknown)}")
    text: dict[str, str] = {}
    for key in ("issuer", "client_id", "client_secret_env", "redirect_uri"):
        if key not in raw:
            raise ConfigError(f"oidc: {key} is required")
        if not isinstance(raw[key], str) or not raw[key]:
            raise ConfigError(f"oidc: {key} must be text")
        text[key] = raw[key]
    for key in ("issuer", "redirect_uri"):
        if urlsplit(text[key]).scheme not in {"http", "https"} or not urlsplit(text[key]).netloc:
            raise ConfigError(f"oidc: {key} must be an http(s) URL")
    groups = raw.get("allowed_groups")
    if not (_names(groups) and groups and all(groups)):
        raise ConfigError("oidc: allowed_groups must name at least one group")
    claim = raw.get("groups_claim", "groups")
    scopes = raw.get("scopes", ["openid", "profile", "email"])
    if not isinstance(claim, str) or not claim:
        raise ConfigError("oidc: groups_claim must be text")
    if not (_names(scopes) and scopes and "openid" in scopes):
        raise ConfigError("oidc: scopes must be a list of text that includes openid")
    engine, reader = raw.get("engine_token_env"), raw.get("reader_token_env")
    names = {"client_secret_env": text["client_secret_env"], "engine_token_env": engine, "reader_token_env": reader}
    for key, name in names.items():
        if name is not None and not (isinstance(name, str) and _ENV_NAME.fullmatch(name)):
            raise ConfigError(f"oidc: {key} must be the name of an environment variable")
    return OidcSettings(
        text["issuer"],
        text["client_id"],
        text["client_secret_env"],
        text["redirect_uri"],
        tuple(groups),
        claim,
        tuple(scopes),
        engine,
        reader,
    )


#: The most events one forwarded batch may hold; a hub refuses a longer one.
MAX_BATCH = 200


@dataclass(frozen=True)
class Forward:
    """Where an IC forwards its events: the hub's address, the variable holding this instance's token there, and
    how many events one POST carries."""

    url: str
    token_env: str
    batch: int = 50


@dataclass(frozen=True)
class Source:
    """An instance a hub accepts forwarded events from; `token_env` names the variable holding its token."""

    name: str
    token_env: str


def runs_adapter(kind: str) -> ModuleType:
    """The runs adapter module `kind` names, which offers `start(url)` and `follow(url, runs, log)`, and optionally `rerun(url)` and `declared_params(url, workflow)`."""
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
    # An instance with a token and neither half of a pull adapter pulls nothing: it draws what the ingest receives.
    push_only = "token_env" in raw and "type" not in raw and "url" not in raw
    for key in ("name",) if push_only else ("name", "type", "url"):
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
    if not push_only:
        try:
            runs_adapter(kind)
        except ConfigError as exc:
            raise ConfigError(f"runs instance {name}: {exc}") from exc
        if not isinstance(url, str):
            raise ConfigError(f"runs instance {name}: url must be text")
    run_safe, domains = raw.get("run_safe", []), raw.get("domains", {})
    if not _names(run_safe):
        raise ConfigError(f"runs instance {name}: run_safe must be a list of workflow names")
    if push_only and run_safe:
        raise ConfigError(f"runs instance {name}: a push-only instance has no start, so run_safe does not apply")
    if not isinstance(domains, dict) or not all(_names(workflows) for workflows in domains.values()):
        raise ConfigError(f"runs instance {name}: domains must map each domain name to a list of workflow names")
    token_env = raw.get("token_env")
    if token_env is not None and not (isinstance(token_env, str) and _ENV_NAME.fullmatch(token_env)):
        raise ConfigError(f"runs instance {name}: token_env must be the name of an environment variable")
    return RunsInstance(
        name,
        kind,
        url,
        tuple(run_safe),
        {domain: tuple(ws) for domain, ws in domains.items()},
        token_env,
        _commit(raw["commit"], name) if "commit" in raw else None,
    )


def _commit(raw: object, instance: str) -> CommitKeys:
    """The `[runs.commit]` table as keys; each refusal names the key to fix."""
    who = f"runs instance {instance}"
    if not isinstance(raw, dict):
        raise ConfigError(f"{who}: commit must be a [runs.commit] table")
    if unknown := sorted(raw.keys() - _COMMIT_KEYS):
        raise ConfigError(f"{who}: commit: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_COMMIT_KEYS))}")
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


def _token_env(raw: object, who: str) -> str:
    if not (isinstance(raw, str) and _ENV_NAME.fullmatch(raw)):
        raise ConfigError(f"{who} token_env must be the name of an environment variable")
    return raw


def _unknown(raw: dict, known: set[str], who: str) -> None:
    if unknown := sorted(raw.keys() - known):
        raise ConfigError(f"{who}: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(known))}")


def _forward(raw: object) -> Forward | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("forward must be a [forward] table")
    _unknown(raw, _FORWARD_KEYS, "forward")
    for key in ("url", "token_env"):
        if key not in raw:
            raise ConfigError(f"forward needs {key}")
    url, batch = raw["url"], raw.get("batch", 50)
    if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
        raise ConfigError("forward url must be an http:// or https:// address")
    token_env = _token_env(raw["token_env"], "forward")
    if not (isinstance(batch, int) and not isinstance(batch, bool) and 1 <= batch <= MAX_BATCH):
        raise ConfigError(f"forward batch must be a whole number from 1 to {MAX_BATCH}")
    return Forward(url, token_env, batch)


def _source(raw: object) -> Source:
    if not isinstance(raw, dict):
        raise ConfigError("sources must be a list of [[sources]] tables")
    for key in ("name", "token_env"):
        if key not in raw:
            raise ConfigError(f"a source needs {key}")
    name = raw["name"]
    if not isinstance(name, str) or not name or "/" in name:
        raise ConfigError("source names must be non-empty text without a /")
    _unknown(raw, _SOURCE_KEYS, f"source {name}")
    return Source(name, _token_env(raw["token_env"], f"source {name}:"))


def _aggregates_only(raw: object) -> bool:
    if not isinstance(raw, bool):
        raise ConfigError("aggregates_only must be true or false")
    return raw


def _sources(raw: object) -> tuple[Source, ...]:
    if not isinstance(raw, list):
        raise ConfigError("sources must be a list of [[sources]] tables")
    sources = tuple(_source(table) for table in raw)
    for at, source in enumerate(sources):
        if any(source.name == earlier.name for earlier in sources[:at]):
            raise ConfigError(f"source {source.name} is configured twice")
        if shared := next((e for e in sources[:at] if e.token_env == source.token_env), None):
            raise ConfigError(
                f"sources {shared.name} and {source.name} share token_env {source.token_env}; each needs its own token"
            )
    return sources


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
    level: Level | None = None
    """The `[level]` flow graph above the Board; none when the config has no such table."""
    hub_retention_days: int = 14
    """A hub keeps raw events for this many days before today, then drops each older day's partition after rolling it up."""
    oidc: OidcSettings | None = None
    """The hub's sign-in (`[oidc]`); a hub refuses to start without it, and an IC instance without `--hub` refuses it."""
    forward: Forward | None = None
    """The hub this instance forwards its events to; none: nothing leaves the machine."""
    sources: tuple[Source, ...] = ()
    """The instances this hub takes forwarded events from, by their tokens."""
    aggregates_only: bool = False
    """A hub that takes aggregates only refuses an instance's opt-in to be named."""
    event_log_retention_days: int = 7
    """`serve` prunes the event log's rows older than this many days, hourly, so the table and every reader's boot replay stay bounded; a reader that was behind the oldest retained row records a gap."""
    event_log_archive_dir: str = "starpulse-archive"
    """Where `serve` writes the event log rows it prunes, one gzip JSONL file per UTC day, before it deletes them; a relative path is beside the config."""
    repos: tuple[Repo, ...] = ()
    """The repositories whose merges apply through the parent's pin bump (`[[repos]]`)."""
    ci: tuple[str, ...] = ()
    """The Board states the shipped `ci` machine is attached to as a sub-flow (`[ci] states`); none: it is not drawn."""
    autopilot: Autopilot = field(default_factory=Autopilot)
    """The policy the autopilot runs under (`[autopilot]`); every key is optional, so no block is the defaults."""
    triggers: tuple[Trigger, ...] = ()
    """The runs to start when a board event arrives (`[[triggers]]`); none: no event starts a run."""
    analytics: Analytics = field(default_factory=Analytics)
    """What the instance's agents' telemetry is read against (`[analytics]`); no table: no roots, stops or triggers."""
    release: Release | None = None
    """The `[release]` table: None releases no task, so a config without it leaves release to whoever does it today."""
    search: Search = field(default_factory=Search)
    """The optional embeddings service that ranks search by meaning (`[search]`); no table: search is lexical only."""

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


def _autopilot(raw: object) -> Autopilot:
    """The `[autopilot]` table's policy, or the defaults when the config has none; a refusal is a `ConfigError`."""
    try:
        return parse_autopilot(raw)
    except AutopilotError as exc:
        raise ConfigError(str(exc)) from exc


def _analytics(raw: object) -> Analytics:
    """The `[analytics]` table, or the empty one when the config has none; a refusal is a `ConfigError`."""
    try:
        return parse_analytics(raw)
    except AnalyticsError as exc:
        raise ConfigError(str(exc)) from exc


def _search(raw: object) -> Search:
    """The `[search]` table, or the lexical-only one when the config has none; a refusal is a `ConfigError`."""
    try:
        return parse_search(raw)
    except SearchError as exc:
        raise ConfigError(str(exc)) from exc


def _triggers(raw: object, runs: Sequence[RunsInstance]) -> tuple[Trigger, ...]:
    """The `[[triggers]]` tables as triggers, each naming a workflow of an instance that can start one."""
    try:
        triggers = parse_triggers(raw)
    except TriggerError as exc:
        raise ConfigError(str(exc)) from exc
    startable = {instance.name for instance in runs if instance.type}
    for at, trigger in enumerate(triggers):
        if (name := trigger.start.partition("/")[0]) not in startable:
            raise ConfigError(f"triggers[{at}]: start names {name}, which is no configured runs instance with a type")
    return triggers


def _release(raw: Mapping[str, object], repos: Sequence[Repo]) -> Release | None:
    """The `[release]` table, or None when the config has none; a table the server cannot apply is a `ConfigError`."""
    if "release" not in raw:
        return None
    table = raw["release"]
    if not isinstance(table, dict) or not table.keys() <= {"settle"}:
        raise ConfigError("release: the [release] table takes only settle")
    if (settle := table.get("settle")) is None:
        return Release()
    if settle != "pin-bump":
        raise ConfigError("release: settle must be pin-bump")
    if not repos:
        raise ConfigError("release: settle = pin-bump needs a [[repos]] entry to say which repositories the parent pins")
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
    """`path`, else `starpulse.toml` in the working directory when it exists, else None (the defaults)."""
    if path is None and Path("starpulse.toml").is_file():
        return Path("starpulse.toml")
    return path


def _retention(value: object, key: str) -> int:
    """The days `key` keeps rows for; a whole number, 1 or more."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{key} must be a whole number of days, 1 or more")
    return value


def _archive_dir(value: object) -> str:
    """The directory `event_log_archive_dir` names; text, not empty."""
    if not isinstance(value, str) or not value:
        raise ConfigError("event_log_archive_dir must be a directory path")
    return value


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
    retention = _retention(raw.get("hub_retention_days", 14), "hub_retention_days")
    log_retention = _retention(raw.get("event_log_retention_days", 7), "event_log_retention_days")
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
    except (ModuleNotFoundError, ValueError):
        found = None
    if found is None:
        raise ConfigError(f"no board adapter of type {kind}")
    url = raw.get("database_url")
    if url is not None and not isinstance(url, str):
        raise ConfigError("database_url must be text")
    oidc = _oidc(raw["oidc"]) if "oidc" in raw else None
    repos = _repos(raw.get("repos", []))
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
        retention,
        oidc,
        _forward(raw.get("forward")),
        _sources(raw.get("sources", [])),
        _aggregates_only(raw.get("aggregates_only", False)),
        event_log_retention_days=log_retention,
        event_log_archive_dir=_archive_dir(raw.get("event_log_archive_dir", "starpulse-archive")),
        repos=repos,
        ci=_ci(raw),
        autopilot=_autopilot(raw.get("autopilot")),
        triggers=_triggers(raw.get("triggers"), runs),
        analytics=_analytics(raw.get("analytics")),
        release=_release(raw, repos),
        search=_search(raw.get("search")),
    )
