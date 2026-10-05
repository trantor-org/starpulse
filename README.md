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
names a Redis it should use instead (`rediss://` reaches it over TLS, and the URL's user and percent-encoded
password sign in to it), and keeps its history in
`starpulse-history.sqlite` beside its config file, or in the working directory without one. The page has no sign-in and listens on every interface, so run it on a machine or network you
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

### Work the board from an agent

```sh
starpulse board --milestone launch --label api   # tasks per column, with dependencies, pull requests and moves
starpulse task show PROJ-45                      # one task: lane, what it waits on, pull requests, moves
starpulse task moves PROJ-45                     # every column it may move to, allowed or refused to the agent
starpulse task move PROJ-45 review               # move it as the agent; a refusal is the verdict, exit 1
starpulse task trace PROJ-45 --flow in-progress  # where the task has been: Board lanes, or one machine's events
starpulse machine show in-progress               # a machine's states, transitions and the tasks now in each
starpulse runs list                              # each workflow as <instance>/<workflow> with its latest status
starpulse runs start prod/nightly                # start a run-safe workflow through Run now; its run id
starpulse watch --task PROJ-45                   # one JSON line per change, until you stop it: wait without polling
starpulse snapshot                               # everything the page draws, as one document
starpulse doctor                                 # does this install work: each check passes or fails, with why
starpulse skills install --claude --codex        # copy the bundled skills into .claude/skills and .agents/skills
starpulse help --agent                           # every verb with its arguments, output keys and exit codes
```

These verbs read the running server (`starpulse serve`) over HTTP: `--server URL`, else `STARPULSE_URL`, else
`http://localhost:8766`. Each writes one JSON document to stdout and nothing to stderr, except `watch`, which writes
one JSON line per change; an error is `{"error": "...", "code": "..."}`. The exit code is 0 for success, 1 for a refused or invalid request, a refused move or a failed `doctor` check, 2 for a usage
error, 3 when the server is unreachable (the error names the address tried) or has no board writer and 4 for something not found. A verb
reads the server on every call and keeps nothing, and `help --agent` is generated from the command parser, so it
lists exactly the verbs there are.

| Verb | Arguments | Document |
|---|---|---|
| `snapshot` | | the server's snapshot: `graphs`, `flows`, `dags`, `pulls`, `claims`, `settled`, ... |
| `board` | `--state`, `--milestone`, `--label`, `--assignee` | `columns`: each `{state, name, tasks}`; a task is `{id, title, lane, assignee, milestone, labels, dependencies, waiting_on, prs, moves}` |
| `task show` | `TASK` | a task as above, with its `description`; a completed or archived task has only its `id` and where it settled as `lane` |
| `task moves` | `TASK` | `task`, `lane` and `moves`: each column the task may move to as `{allowed, reason, skill}`, as the agent meets it |
| `task move` | `TASK`, `TO`, `--session` | `ok`, `task`, `to`, `reason`, `skill` and `advice`: the move made, or the refusal and the skill that satisfies it (exit 1); exit 3 when the board has no writer |
| `task trace` | `TASK`, `--flow` | `task`, `flow` (null without `--flow`), `path` and `steps`; the Board's `{at, from, to}` lane changes, or with `--flow` that machine's `{at, event, state}`, oldest first; an unknown flow exits 4, a task never seen has an empty `path` |
| `machine list` | | `machines`: each `{name, states, tasks}` with its state ids and its live task count |
| `machine show` | `NAME` | `name`, `states` (each `{id, name, initial, final, count, tasks}`) and `transitions`; an unknown machine exits 4 and names those drawn |
| `runs list` | | `runs`: each workflow as `{workflow, status, raw, run_id, started_at, finished_at}` with `workflow` `<instance>/<workflow>`, and `error`, the runs adapters' error or null |
| `runs start` | `WORKFLOW` | `workflow` and `run_id`: starts `<instance>/<workflow>` through the server's Run now path, so only a workflow in the instance's `run_safe` starts and only from the loopback or private network (exit 1 when refused); an instance with no start exits 3, a workflow outside `run_safe` exits 4 |
| `watch` | `--machine`, `--task` | one line per change after the connect snapshot, `{event, data}` with `event` `task`, `move`, `pulls`, `claim` or `dags` and `data` the server's delta; `--machine` keeps that machine's changes (`board` takes `task`, `pulls` and `claim`), `--task` that task's, and either drops `dags`; an unknown machine exits 4, the server ending the stream exits 3, and an interrupt exits 0 |
| `doctor` | `--config` | `ok` and `checks`: each `{check, status, reason}`, `status` `pass` or `fail`; exit 1 when any fails |
| `skills list` | `--user` | `scope` and `skills`: each `{name, description, claude, codex}`, each harness `absent`, `installed`, `outdated` or `modified` |
| `skills install` | `--claude`, `--codex`, `--user`, `--force` | `scope` and `installed`: each `{harness, skill, path, was}`; exit 1 when a copy was modified since install |
| `help --agent` | | `exit_codes` and `verbs` |

A move carries the actor that makes it. The machine YAML names, per event, who fires it (`writers`), and each move
the server offers lists them as `writers`; `POST /api/move` takes `{task, to, actor}` with `actor` `operator` when
absent, which is what the page sends. The server refuses an actor outside the event's writers before the board
writer is asked, so a move declared for `operator` alone (sending an In Progress task back to Ready) is refused to
`starpulse task move`, which always moves as `agent`. A board adapter's `writer` receives that actor as its third
argument: `writer(task, status, actor)`. `/api/move` is unauthenticated on the LAN, so this stops an agent's
accident, not an adversary.

A move may also name the mover's session: `POST /api/move` takes `{task, to, actor, session}`, and `starpulse task move`
sends `--session`, else `STARPULSE_SESSION`. A move that names one calls the writer with it as a fourth argument,
`writer(task, status, actor, session)`; one that names none calls it with three, so a writer written before sessions
keeps working. The writer records the session as the task's holder when the move is a claim, `BoardTask.holder`
carries it back, and a `Written.advice` string rides in the move's answer (`advice` in the CLI document, empty when
the writer has none). The Backlog.md adapter's writer records the holder as a `**Holder:** <session>` line in the
task's notes, in the same edit as the `In Progress` status, because the Backlog CLI drops a frontmatter key it
does not know.

`doctor` runs every check even when one fails, so one call names every fault. The checks: `config` (the config file
loads), `redis` (`REDIS_URL` answers, or docker or podman can start the Valkey container the server would use),
`server` (it answers `/api/snapshot`), `adapter:board` and one `adapter:<name>` per `[[runs]]` instance (it is
producing: the Board is read, the instance lists workflows and reports no error), `gh` (installed and logged in, which
the pull request reader needs) and `stream-lag` (no consumer group of `machine:events` or `runs:events` is more than
100 entries behind, entries delivered but not yet acknowledged included, and none whose lag Redis cannot measure). A
check that needs a server or Redis that is down fails too, saying so.

`skills` reads no server. The package bundles two skills, `operating-starpulse-board` (what to work next, why a task
cannot move, moving it) and `setting-up-starpulse` (starting the server, Redis, config, `doctor`), and `skills install`
copies them to `.claude/skills` (`--claude`) or `.agents/skills` (`--codex`) in the working directory, or with `--user`
to `~/.claude/skills` or `~/.agents/skills`. An install records what it wrote, so a copy you edited afterwards is
refused (exit 1) until you pass `--force`, while one the package has since updated is replaced; `skills list` reports
which of the two each copy is.

`waiting_on` is the dependencies not yet completed. `prs` are the task's pull request links, each with the checks,
merged state and open review threads the server last read when it has them.

## Configure

`starpulse serve --config starpulse.toml` reads one TOML file; `starpulse.toml` in the working directory is read
when it exists. Credentials never go in it: they come from the environment (`REDIS_PASSWORD` and the ACL user `REDIS_USERNAME`, and a database
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
# path = "backlog"       # the project's backlog/ directory, relative to this file
# command = "backlog"    # the Backlog.md CLI that writes a move (`backlog task edit <id> -s <status>`)
# machine = "board.yaml" # a machine file for the Board: its transitions and `writers` decide which moves are offered, and to whom

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
- and optionally a `writer(task, status, actor)` for moves made on the page or by an agent (each task's `moves` may
  list the `writers` the machine declares per event), an `assign` for assignee changes, a `read`, `edit` and `archive` for the full task record and guarded edits and
  archives (`edit` needs `read`; the snapshot's `capabilities` says which the board has), and its own `history`.

`starpulse.upstream_backlog` is the reference adapter: it polls a Backlog.md project's Markdown files, takes
the machine from the project's own statuses (any lane reaches any other, unless `machine` names a machine file
whose states are those lanes and whose `writers` reserve a move to an actor, such as `operator`), and writes moves
with the `backlog` CLI, answering a failed write with the CLI's output. An adapter with a writer subclasses
`BoardAdapterKit` with `writer` set, and the kit then checks that a move the operator may make is written and one
the machine leaves to the operator is refused to the agent. Name your module in `[board] type` and StarPulse imports it.

## Public surface

What a release keeps compatible; a minor `0.y` release may break it, and its notes say so. Everything else in the package is
internal and can change in any release.

- The `starpulse` command line: its verbs, their JSON output and their exit codes.
- The documented entry point `python -m starpulse.claude_code`.
- The config file's keys and the machine YAML with its JSON Schema (`machine.schema.json`).

The modules an adapter may import, each exporting exactly the names in its `__all__`:

- `starpulse.board`: the board adapter seam (`Board`, `Written` and the writer and task protocols).
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
[`bench/`](bench/README.md) holds the hub-ingest and instance event-log benchmarks.

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
