"""The shape of `starpulse.toml`, declared once: its keys, types, defaults and what each does.

`config.load` takes its key sets and defaults from these models, and `config_reference` renders the settings reference
in `docs/serving.md` from their JSON Schema, so a key added here shows up in the doc and a key the doc names is a key
the loader accepts. A table another module parses (`[board]`, `[scheduler]`, ...) is a free-form mapping here, with a
description that says where its keys are documented. The loader's checks stay in `config.load`, which words each refusal
for the operator; the constraints below describe them.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from starpulse.views.services import SLOW_READ_S

#: An environment variable's name: the setting holds the name, never the value.
EnvName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]

#: The memory limit, in megabytes, of each `starpulse worker` context when `worker_memory` does not name one.
WORKER_MEMORY_MB = {
    "pulls": (768, 1536),
    "scheduler": (384, 768),
    "runs": (512, 1024),
    "flow-metrics": (384, 768),
    "search": (384, 768),
    "board": (768, 1536),
}


class _Table(BaseModel):
    """A config table: a key it does not declare is refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CommitFile(_Table):
    """The `[runs.commit]` table."""

    model_config = ConfigDict(title="[runs.commit]")

    after: EnvName | None = Field(
        default=None, description="The merge commit the run applies: pairs the run with that merge."
    )
    before: EnvName | None = Field(default=None, description="The commit before it.")
    force: EnvName | None = Field(default=None, description="The parameter that marks a forced run.")
    task: EnvName | None = Field(
        default=None,
        description="The task a run is for: pairs a run with a task's entry into a lane (any Board event but MERGED).",
    )


class RunsInstanceFile(_Table):
    """One `[[runs]]` table."""

    model_config = ConfigDict(title="[[runs]]")

    name: str = Field(
        min_length=1,
        pattern=r"^[^/]+$",
        description="The instance's name, unique; its workflows are drawn as `<name>/<workflow>`.",
    )
    type: str = Field(
        description=(
            "The runs adapter: a module under `starpulse` or the dotted path of "
            "one an installed package provides. It offers `start(url)` and `follow(url, runs, log)`, and optionally "
            "`rerun(url)` and `declared_params(url, workflow)`, the parameter names a workflow declares, which "
            "`doctor` reads. See Runs adapters for what a built-in adapter reads and serves."
        ),
    )
    url: str = Field(
        description=(
            "What the adapter reads. A built-in adapter is an opt-in worker: you run `starpulse worker <adapter> "
            "--config <this file>`, `serve` starts it nowhere, and, with it down or never started, the page shows "
            "this instance with the error \"the <adapter> worker has not reported\" or \"last reported Ns ago\" (its "
            "beat is older than 60s)."
        ),
    )
    run_safe: list[str] = Field(default=[], description="The workflows the page's Run now may start.")
    domains: dict[str, list[str] | dict[str, list[str]]] = Field(
        default={},
        description=(
            "How the page groups this instance's workflows: each domain is a list of workflow names, or a table of "
            "process name to workflow list."
        ),
    )
    commit: CommitFile | None = Field(
        default=None,
        description=(
            "The run parameters that carry what a run applies, so the Ledger pairs a run with its merge for certain. "
            "Each key names a parameter; a key left out is a parameter this instance has none of."
        ),
    )


class ProducerFile(_Table):
    """One `[[producers]]` table."""

    model_config = ConfigDict(title="[[producers]]")

    name: str = Field(
        min_length=1,
        pattern=r"^[^/]+$",
        description="The CloudEvents `source` its events carry; unique.",
    )
    token_env: EnvName = Field(
        description="The environment variable holding its bearer token, never the token; no two producers share one."
    )
    machines: list[str] = Field(
        default=[],
        description="The drawn machines it may write; leave out with `actors` for a producer that only reports runs.",
    )
    actors: list[str] = Field(default=[], description="The actors it may write as.")
    adapter: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "A run adapter type whose own status labels its Step events carry, read through that adapter's "
            "`status_of`."
        ),
    )


class RepoFile(_Table):
    """One `[[repos]]` table."""

    model_config = ConfigDict(title="[[repos]]")

    name: str = Field(
        min_length=1,
        pattern=r"^[^/]+$",
        description="The repository as its pull request links spell it.",
    )
    path: str = Field(
        min_length=1, description="Where the parent holds the repository as a submodule: relative, inside the parent."
    )
    applied_by: Literal["pin-bump"] = Field(description="How its merges are applied; only `pin-bump`.")


class MemoryFile(_Table):
    """One `[worker_memory.<context>]` table."""

    model_config = ConfigDict(title="[worker_memory.<context>]")

    soft_mb: int | None = Field(
        default=None, ge=1, description="Past this the child is replaced: a new one starts, then the old one stops."
    )
    hard_mb: int | None = Field(
        default=None, ge=1, description="Past this the child is killed and restarted. Above `soft_mb`."
    )


class ReleaseFile(_Table):
    """The `[release]` table."""

    model_config = ConfigDict(title="[release]")

    settle: Literal["pin-bump", "release"] | None = Field(
        default=None,
        description=(
            "When a dependency counts as settled; left out, it settles when its task is Done. `pin-bump`: a "
            "dependency citing a pull request in a `[[repos]]` repository settles only once the parent pins its "
            "merge commit. `release`: a dependency citing a pull request in `repo` settles only once the running "
            "build contains its merge commit."
        ),
    )
    repo: str | None = Field(
        default=None, description='`settle = "release"` only: the repository the running build is released from.'
    )


class CiFile(_Table):
    """The `[ci]` table."""

    model_config = ConfigDict(title="[ci]")

    states: list[str] = Field(
        min_length=1,
        description=(
            "The Board state ids the shipped `ci` machine is attached to as a sub-flow; one the Board lacks is "
            "refused. StarPulse ships one `ci` machine, which GitHub moves and StarPulse only observes (its `source` "
            "is GitHub). With `gh` available, each task with a PR is one agent in that flow, and its trail is the "
            "PR's pushes, check results, re-runs, conflicts, rebases and merge, read from GitHub every minute and "
            "kept in the event log (`machine:events`)."
        ),
    )


class ConfigFile(_Table):
    """The whole `starpulse.toml`."""

    model_config = ConfigDict(title="Top level")

    tracker_url: str | None = Field(
        default=None,
        description=(
            "The tracker's web address: a task links to `<tracker_url>/tasks/<id>`. Unset, it opens in the page's "
            "own Kanban."
        ),
    )
    database_url: str | None = Field(
        default=None,
        description=(
            "The SQLAlchemy URL of the history store; unset, `starpulse-history.sqlite` beside the config. The "
            "credentials never live here; they come from the driver's environment, such as `PGPASSWORD`."
        ),
    )
    event_log_retention_days: int = Field(
        default=7,
        ge=1,
        description=(
            "How long `serve` keeps the event log's rows: it prunes older ones at start and hourly, so the table, a "
            "SQLite file and every reader's replay at boot stay bounded. A reader that was down longer than this "
            "resumes at the oldest kept row and records the span it missed in `starpulse_gaps`. A whole number of "
            "days."
        ),
    )
    event_log_archive_dir: str = Field(
        default="starpulse-archive",
        min_length=1,
        description=(
            "Where `serve`'s History child writes each row it prunes, before it deletes the row (see Event log "
            "archive): a directory, relative to this file unless absolute."
        ),
    )
    telemetry_loki_url: str | None = Field(
        default=None,
        description=(
            "The Loki base URL the harness adapters push each telemetry signal to, one log line per signal in "
            '`{job="starpulse-signals"}`, and the analytics views read back. Unset, the signals go to the event log. '
            "Give the stream its own Loki `retention_stream` rule to keep it as long as the event log."
        ),
    )
    slow_read_seconds: float = Field(
        default=SLOW_READ_S,
        gt=0,
        description=(
            "The seconds a `GET /api/pulls` read may take, from accept to the last byte written, before `serve` logs "
            "a `slow_read` line for it: `queue_s`, `compute_s` and `write_s`, the seconds it waited for a handler "
            "thread, computed its answer and wrote it, `in_flight`, the `/api/pulls` reads running when it began, "
            "and `busy` and `streams`, the request workers in use (the read itself included) and the streams open "
            "when it was accepted. No other route is timed."
        ),
    )
    worker_memory: dict[Literal["pulls", "scheduler", "runs", "flow-metrics", "search", "board"], MemoryFile] = Field(
        default={},
        description=(
            "The memory limits (proportional size on Linux, resident size on macOS) `serve` holds each worker child "
            "to, in megabytes (see Worker processes), set as `[worker_memory.<context>]` with either key left out. "
            "Past `soft_mb` it replaces the child, past `hard_mb` it kills and restarts it. Defaults, soft/hard: "
            + ", ".join(f"`{context}` {soft}/{hard}" for context, (soft, hard) in WORKER_MEMORY_MB.items())
            + "."
        ),
    )
    mode: Literal["ic"] = Field(default="ic", description="`ic`, the one value: one person on one machine.")
    tls_cert: str | None = Field(
        default=None,
        description="The TLS certificate, relative to this file's directory; set with `tls_key`, else both unset.",
    )
    tls_key: str | None = Field(
        default=None, description="The TLS private key, relative to this file's directory; set with `tls_cert`."
    )
    session_start_url: str | None = Field(
        default=None,
        description=(
            "The session-start service a started task is sent to (`POST <url>/start/TASK-N?harness=&mode=`); unset: "
            "nothing can be started."
        ),
    )
    harnesses_file: str | None = Field(
        default=None,
        description="A file, relative to this one, that declares the tiers and per-harness models.",
    )
    pull_requests: bool = Field(
        default=True,
        description=(
            "With `gh` on the PATH, `serve` keeps a pull request store, current from the lifecycle events, that "
            "`/api/pulls`, the `ci` trail and `[release]` read. false never updates it: no event is applied, `POST "
            "/api/pulls/refresh` answers 404, tasks carry no PR state, and `/api/pulls` answers only from rows the "
            "database already holds. Set it on a second instance beside one that reads the same repositories, so "
            "one store is kept."
        ),
    )
    refresh_token_env: EnvName | None = Field(
        default=None,
        description=(
            "Lets a producer that just saw a pull request close have its record read now instead of at the next "
            'minute\'s refresh: `POST /api/pulls/refresh` with `{"repo": "<owner>/<name>", "number": 12}` and '
            "`Authorization: Bearer <token>`. The PR store's thread reads that pull request alone (one single-PR "
            "GraphQL read, no listing) and publishes it as a refresh does; one asked for during a refresh is read "
            "after the repository in hand, ahead of that refresh's projection. The minute's refresh stays the "
            "fallback. 202 queued; 401 for a missing or wrong token; 403 for a repository this instance does not "
            "track; 400 for any other body. The value is the name of an environment variable, never the token; "
            "unset, or with no `gh` on the PATH, the route answers 404, and a named variable that is empty stops "
            "`serve`."
        ),
    )
    take_over_command: list[str] | None = Field(
        default=None,
        min_length=1,
        description=(
            'The command `POST /api/take-over` runs, as an argv: StarPulse appends the task id (`{"task": '
            "\"TASK-7\"}` in the body) and the command asks the task's workflow engine to flip that task's workflow "
            "to interactive, so it types nothing more into the task's session. Exit 0: sent (200). Exit 1: the "
            "task has no running workflow (409). Any other exit: an error, with the command's stderr. 404 when this "
            "is unset. The command is the only place a workflow engine appears."
        ),
    )
    runs: list[RunsInstanceFile] = Field(default=[], description="One instance of a runs adapter per `[[runs]]` table.")
    producers: list[ProducerFile] = Field(
        default=[],
        description=(
            "A system that posts machine events as CloudEvents (see docs/sources.md, Post machine events as "
            "CloudEvents). `POST /api/machine-events` and the gRPC `starpulse.v1.CloudEventsIngest` answer 404 "
            "until one is declared. A producer writes only the machines and actors listed here."
        ),
    )
    repos: list[RepoFile] = Field(
        default=[],
        description=("A repository whose merges apply through the parent's pin bump rather than a run of their own."),
    )
    ci: CiFile | None = Field(
        default=None, description="Draws each task's pull-request CI as a sub-flow of these Board states."
    )
    release: ReleaseFile | None = Field(
        default=None,
        description=(
            "Releases Waiting tasks natively. With the table present, `serve` moves a Waiting task to Ready once "
            "every task it depends on is Done (see Release); with no `[release]` table it releases none. The board "
            "must edit tasks and draw `waiting` and `ready` lanes, else `serve` refuses to start."
        ),
    )
    board: dict[str, Any] = Field(
        default={},
        description=(
            "The board adapter: `type` names a module under `starpulse` or the dotted path of one an installed "
            "package provides, and the rest of the table is that adapter's settings, shown in the Board examples "
            'above. With no `[board]` table the view draws its own Markdown board, `type = "native"`.'
        ),
    )
    level: dict[str, Any] | None = Field(
        default=None, description="The flow graph drawn above the Board (`starpulse.flow_metrics.model.level`)."
    )
    scheduler: dict[str, Any] | None = Field(
        default=None, description="The scheduler's policy; every key is optional (see Scheduler)."
    )
    analytics: dict[str, Any] | None = Field(
        default=None,
        description="What harness telemetry is read against for missed skill loads and trace clusters (see docs/sources.md).",
    )
    search: dict[str, Any] | None = Field(
        default=None, description="Ranks search by meaning as well as by words (see `search` in docs/cli.md)."
    )
    project: dict[str, Any] | None = Field(
        default=None, description="The project's own command line for each step a shipped skill names."
    )
    cursor_context: dict[str, Any] | None = Field(
        default=None, description="Holds Cursor task sessions to a context limit (see docs/sources.md)."
    )
    read_model: Any = Field(
        default=None,
        deprecated=True,
        description="Retired: the read model is the only board reader; accepted so a config that still names it loads.",
    )
