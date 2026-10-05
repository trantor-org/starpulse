# StarPulse

See the flow of work: your scheduler's workflows, the lifecycle your tasks move through, and the agents and
people moving them, live on one page.

**[Live demo](https://trantor-org.github.io/flow-demos/main/flow-view.html)**: a real board's structure with
every task replaced by a synthetic one, running in your browser with no server.

## What it draws

- **Tasks on their lifecycle.** Each board status is a state on a machine, and a task travels the transitions
  as it moves. The default board is a [Backlog.md](https://github.com/MrLesk/Backlog.md) project; a Kanban view
  shows the same tasks as columns, and moves made there are written back to the board when its adapter has a
  writer.
- **Workflow runs.** Each workflow is drawn as its step graph with its latest run. [Dagu](https://github.com/dagu-org/dagu) is
  read directly; any other scheduler reports its runs with `starpulse emit`.
- **Agents at work.** A Claude Code session's OpenTelemetry log export moves the session through its own
  machine, so you see which agent is prompting, running a tool or waiting.
- **History.** Every move is kept, so hovering a task traces the path it took.

## Quickstart

You need [uv](https://docs.astral.sh/uv/), and Docker or Podman.

```sh
cd your-project          # a Backlog.md project: the one with a backlog/ directory
uvx starpulse serve
```

Open <http://localhost:8766>. StarPulse starts a Valkey container for its event streams unless `REDIS_URL`
names a Redis it should use instead, and keeps its history in `starpulse-history.sqlite` beside its config file, or in
the working directory without one. The page has no sign-in and listens on every interface, so run it on a machine or network you
trust.

`starpulse serve --port 8800 --hours 24` changes the port and how far back a task's latest move counts toward
where it is drawn (6 hours by default). The Admin page's Server card overrides that window for everyone
viewing, and `starpulse-settings.json` beside the config keeps the override across restarts.

### Show your Claude Code sessions

Run the receiver beside the server, then start Claude Code with its log export pointed at it:

```sh
uvx --from starpulse python -m starpulse.claude_code

CLAUDE_CODE_ENABLE_TELEMETRY=1 OTEL_LOGS_EXPORTER=otlp OTEL_EXPORTER_OTLP_PROTOCOL=http/json \
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 OTEL_LOG_TOOL_DETAILS=1 \
OTEL_RESOURCE_ATTRIBUTES="vcs.ref.head.name=$(git branch --show-current)" claude
```

The receiver decodes each export but publishes only which session moved, on which event and when; prompt,
reply and tool text is neither stored nor forwarded.

### Report runs from any scheduler

```sh
starpulse emit start --workflow nightly --run 2026-10-03 --status running
starpulse emit end   --workflow nightly --run 2026-10-03 --status succeeded --step load --depends fetch
```

A workflow no adapter lists is drawn from the step graph its `emit` calls add up to, and that graph is kept in
the history store across restarts.

## Configure

`starpulse serve --config starpulse.toml` reads one TOML file; `starpulse.toml` in the working directory is read
when it exists. Credentials never go in it: they come from the environment (`REDIS_PASSWORD`, and a database
driver's own, such as `PGPASSWORD`).

```toml
# The tracker's web address: a task links to `<tracker_url>/tasks/<id>`.
tracker_url = "https://tracker.example.com"

# History in Postgres instead of SQLite; install the extra with `uvx --from 'starpulse[postgres]' starpulse serve`.
database_url = "postgresql+psycopg://db.example.com/starpulse"

# The board adapter: a module under `starpulse`, or the dotted path of one an installed package provides.
# The rest of the table is that adapter's settings.
[board]
type = "upstream_backlog"

# One instance of a runs adapter, a module under `starpulse` or the dotted path of one an installed package provides
# (it offers `start(url)` and `follow(url, runs, group)`); its workflows are drawn as `<name>/<workflow>`.
[[runs]]
name = "dagu"
type = "dagu"
url = "http://dagu.example.com:8080"
run_safe = ["nightly"]                   # the workflows the page's Run now may start
domains = { Data = ["nightly", "etl"] }  # how the page groups this instance's workflows
```

## Write a board adapter

A board adapter connects StarPulse to a tracker. It is a module with a `board(settings, base)` function that
returns a `starpulse.board.Board`: `settings` is the rest of the `[board]` table and `base` is the config file's
directory. The `Board` says:

- which lifecycle machines the page draws (`machines`),
- how the tracker's tasks reach the page (`start`, which feeds each task as it changes, and `keys`, the task
  keys it recognizes),
- and optionally a `writer` for moves made on the page, an `assign` for assignee changes, and its own `history`.

`starpulse.upstream_backlog` is the reference adapter: it polls a Backlog.md project's Markdown files and takes
the machine from the project's own statuses. Name your module in `[board] type` and StarPulse imports it.

## Public surface

What a release keeps compatible; a minor `0.y` release may break it, and its notes say so. Everything else in the package is
internal and can change in any release.

- The `starpulse` command line: its verbs, their JSON output and their exit codes.
- The documented entry point `python -m starpulse.claude_code`.
- The config file's keys and the machine YAML with its JSON Schema (`machine.schema.json`).

The modules an adapter may import, each exporting exactly the names in its `__all__`:

- `starpulse.board`: the board adapter seam (`Board`, `Written` and the writer protocols).
- `starpulse.contracts`: the board, machine-event and runs records, their JSON Schemas, and `RunsSink`.
- `starpulse.adapter_kit`: the test kit an adapter author runs against their adapter.
- `starpulse.machine_definition`: loading and validating a machine, and the `Registry` of guards and actions.
- `starpulse.config`: loading the config file, and the runs adapter a `type` names.
- `starpulse.otlp`: decoding Claude Code's OpenTelemetry log export.

A package test pins this list and each module's names, so adding or removing one is a reviewed change.

## Develop

```sh
git clone https://github.com/trantor-org/starpulse && cd starpulse
uv sync
pnpm --dir starpulse/web install && pnpm --dir starpulse/web build   # the page, built into starpulse/static
uv run starpulse serve
```

`uv run pytest` runs the suite; its integration tests start Redis and Postgres containers, so Docker must run.
`pnpm --dir starpulse/web run check` typechecks, lints, tests and builds the page.

## Contributing

Open an [issue](https://github.com/trantor-org/starpulse/issues/new/choose) for a bug, a feature or a question.
Pull requests come from collaborators; [CONTRIBUTING.md](CONTRIBUTING.md) has how both work.

## Releases

StarPulse is versioned `0.y.z` until its interfaces settle: a minor version can break the config file, the
adapter contract or the command line, and a patch release never does. Each release is a
[GitHub Release](https://github.com/trantor-org/starpulse/releases) whose notes list the pull requests it
contains, published to PyPI as `starpulse`.

## License

MIT; see [LICENSE](LICENSE).
