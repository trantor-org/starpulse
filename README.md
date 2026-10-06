# StarPulse

See the flow of work: your scheduler's workflows, the lifecycle your tasks move through, and the agents and
people moving them, live on one page.

**[Live demo](https://trantor-org.github.io/starpulse-demo/main/flow-view.html)**: a demo board with synthetic
tasks, running in your browser with no server.

## What it draws

- **Tasks on their lifecycle.** Each board status is a state on a machine, and a task travels the transitions
  as it moves. The default board is StarPulse's own: Markdown task files under `.starpulse/board/`, created empty
  the first time you serve. A [Backlog.md](https://github.com/MrLesk/Backlog.md) project is one `[board]` setting
  away; a Kanban view shows the same tasks as columns, and moves made there are written back to the board when its
  adapter has a writer.
- **Workflow runs.** Each workflow is drawn as its step graph with its latest run. [Dagu](https://github.com/dagu-org/dagu) and
  [GitHub Actions](https://docs.github.com/actions) are read directly; any other scheduler reports its runs with
  `starpulse emit`.
- **Agents at work.** A Claude Code session's OpenTelemetry log export moves the session through its own
  machine, so you see which agent is prompting, running a tool or waiting.
- **History.** Every move is kept, so hovering a task traces the path it took.

## Quickstart

You need [uv](https://docs.astral.sh/uv/).

```sh
cd your-project
uvx starpulse serve
```

Open <http://localhost:8766>. The first serve creates `.starpulse/board/` in the working directory (beside the config file when `--config`
names one): a `config.yml`
holding the project name (that directory's name, the team its tasks are in), the lanes (To Do, In Progress, Done) and an empty `tasks/` directory, one Markdown file per task. The
Kanban view starts with no tasks: **New task**, at the top right beside the task count, opens a form for its title, description, priority, labels,
milestone, assignee, dependencies and acceptance criteria and adds it to the first column, and
**Connect a tracker** opens the `[board]` setting for each public adapter. If the directory has a Backlog.md project (`backlog/config.yml`), serve prints one
line naming it and the `[board] type = "upstream_backlog"` setting that shows it instead (see Configure); the page's
snapshot carries the same line as `hint`, and Connect a tracker shows it. StarPulse keeps its event log and history in
`starpulse-history.sqlite` beside its config file, or in the working directory without one. The page has no sign-in and listens on this machine only (`127.0.0.1`): `--host 0.0.0.0` widens it to
every interface so another computer on your network can open it, which you do only on a network you trust. A write (move, edit,
start, run, history window) is refused unless it is a JSON request (`Content-Type: application/json`) that either names no
`Origin`, as a script or `curl` does, or names this server's own, so a web page on another site cannot write through your browser.

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

A producer on another host, or an engine that can only send webhooks (Cronicle, Rundeck, a GitHub `workflow_run`
relay), posts the same event to the server instead. Name an environment variable for the instance's token in the
config (`token_env`, below), set it where `serve` runs, and send the token as a bearer:

```sh
curl -X POST http://localhost:8766/api/runs/events -H "Authorization: Bearer $CRON_INGEST_TOKEN" \
  -d '{"phase": "start", "workflow": "cron/nightly", "run_id": "2026-10-03", "status": "running"}'
```

The body takes `emit`'s fields as JSON (`phase`, `workflow`, `run_id`, `status`, and optionally `time`, `step` and
`depends`) with the workflow named `<instance>/<workflow>`. A token pushes only its own instance's workflows: a
missing or wrong token answers 401, another instance's workflow 403, an event the contract does not allow 400, and
none of them writes anything. The page draws an accepted event as `pushed/<instance>/<workflow>`.

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
starpulse analytics health --hours 72            # dwell and WIP per state, throughput and stuck tasks, with gap warnings
starpulse snapshot                               # everything the page draws, as one document
starpulse doctor                                 # does this install work: each check passes or fails, with why
starpulse skills install --claude --codex        # copy the bundled skills into .claude/skills and .agents/skills
starpulse help --agent                           # every verb with its arguments, output keys and exit codes
```

Four verbs work on files, and only `demo` without `--mockup` reads the server; each writes one JSON document the same way:

```sh
starpulse machine validate .starpulse/machines/*.yaml   # schema and compile errors, each with its file and line
starpulse machine import mermaid flow.mmd               # draft a machine file from a stateDiagram-v2 diagram
starpulse config check --config starpulse.toml          # unknown keys by name, and the effective config with defaults
starpulse demo --out demo.html                          # the self-contained demo page (reads the server's snapshot)
```

These verbs read the running server (`starpulse serve`) over HTTP: `--server URL`, else `STARPULSE_URL`, else
`http://localhost:8766`. Each writes one JSON document to stdout and nothing to stderr, except `watch`, which writes
one JSON line per change; an error is `{"error": "...", "code": "..."}`. The exit code is 0 for success, 1 for a refused or invalid request, a refused move or a failed `doctor` check, 2 for a usage
error, 3 when the server is unreachable (the error names the address tried) or has no board writer and 4 for something not found. A verb
reads the server on every call and keeps nothing, and `help --agent` is generated from the command parser, so it
lists exactly the verbs there are.

| Verb | Arguments | Document |
|---|---|---|
| `snapshot` | | the server's snapshot: `graphs`, `flows`, `dags`, `pools`, `pulls`, `claims`, `settled`, ... |
| `board` | `--state`, `--milestone`, `--label`, `--assignee` | `columns`: each `{state, name, tasks}`; a task is `{id, title, lane, assignee, milestone, labels, dependencies, waiting_on, prs, moves}` |
| `task show` | `TASK` | a task as above, with its `description`; a completed or archived task has only its `id` and where it settled as `lane` |
| `task moves` | `TASK` | `task`, `lane` and `moves`: each column the task may move to as `{allowed, reason, skill}`, as the agent meets it |
| `task move` | `TASK`, `TO`, `--session` | `ok`, `task`, `to`, `reason`, `skill` and `advice`: the move made, or the refusal and the skill that satisfies it (exit 1); exit 3 when the board has no writer |
| `task trace` | `TASK`, `--flow` | `task`, `flow` (null without `--flow`), `path` and `steps`; the Board's `{at, from, to}` lane changes, or with `--flow` that machine's `{at, event, state}`, oldest first; an unknown flow exits 4, a task never seen has an empty `path` |
| `machine list` | | `machines`: each `{name, states, tasks}` with its state ids and its live task count |
| `machine show` | `NAME` | `name`, `states` (each `{id, name, initial, final, count, tasks}`) and `transitions`; an unknown machine exits 4 and names those drawn |
| `machine validate` | `PATH...` | `ok` and `machines`: each `{path, ok, errors}`, an error `{file, line, message}` (`line` is null when the compiler cannot place it); exit 1 when any file is refused. A guard or action name is taken as the adapter's to register |
| `machine import mermaid` | `SOURCE`, `--out` | `written`: the new file, by default `.starpulse/machines/<name>.yaml`; an existing file is refused (exit 1), a missing source is exit 4 |
| `runs list` | | `runs`: each workflow as `{workflow, status, raw, run_id, started_at, finished_at}` with `workflow` `<instance>/<workflow>`, and `error`, the runs adapters' error or null |
| `runs start` | `WORKFLOW` | `workflow` and `run_id`: starts `<instance>/<workflow>` through the server's Run now path, so only a workflow in the instance's `run_safe` starts and only from the loopback or private network, as JSON with no foreign `Origin` (exit 1 when refused); an instance with no start exits 3, a workflow outside `run_safe` exits 4 |
| `watch` | `--machine`, `--task` | one line per change after the connect snapshot, `{event, data}` with `event` `task`, `move`, `pulls`, `claim` or `dags` and `data` the server's delta; `--machine` keeps that machine's changes (`board` takes `task`, `pulls` and `claim`), `--task` that task's, and either drops `dags`; an unknown machine exits 4, the server ending the stream exits 3, and an interrupt exits 0 |
| `analytics health` | `--hours`, `--stuck-hours` | `now`, `window_s`, `stuck_after_s`, `states`, `throughput`, `stuck` and `warnings`, below |
| `config check` | `--config` | `ok`, `file`, `unknown_keys`, `errors` and `config`, the effective config with every default filled in (null when it does not load); exit 1 when it does not load |
| `demo` | `--out`, `--mockup`, `--server` | `written`: the HTML file; it reads the server's snapshot, or a design mockup directory with `--mockup` |
| `doctor` | `--config` | `ok` and `checks`: each `{check, status, reason}`, `status` `pass` or `fail`; exit 1 when any fails |
| `skills list` | `--user` | `scope` and `skills`: each `{name, description, claude, codex}`, each harness `absent`, `installed`, `outdated` or `modified` |
| `skills install` | `--claude`, `--codex`, `--user`, `--force` | `scope` and `installed`: each `{harness, skill, path, was}`; exit 1 when a copy was modified since install |
| `help --agent` | | `exit_codes` and `verbs` |

`analytics health` reads `GET /api/analytics/health[?hours=N][&stuck_hours=N]` (a window of 168 hours and a stuck
threshold of 24 by default), the Board's flow health from the history's lane changes. `states` lists each Board state
with `wip`, the tasks in it now, and for a state that is not final the `visits`, `mean_s` and `max_s` of the stays that
ended inside the window or are still going, `open` of them: a task still in its state counts to now, so its stay is
flagged rather than left out. `throughput` is `{count, per_day}`, the entries into a final state in the window.
`stuck` lists each task whose current stay in a state that is neither the first nor a final one has lasted
`stuck_hours` or longer, longest first, each `{task, state, since, dwell_s, counted_to_now}`. `warnings` carry each
gap the history recorded (`kind` `gap`: entries trimmed before it read them, so counts may miss them) and each lane
the Board machine has no state for. History starts at a task's first recorded lane change, so a stay before it is not
counted. The endpoint is 400 for an `hours` or `stuck_hours` that is no positive number, and 501 when the history
(a board adapter's own) does not list every task's lane changes through `lane_rows()` and `gaps()`.

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
the writer has none). The native and Backlog.md adapters' writers record the holder as a `**Holder:** <session>` line in the
task's notes, in the same edit as the `In Progress` status, because the Backlog CLI drops a frontmatter key it
does not know.

`doctor` runs every check even when one fails, so one call names every fault. The checks: `config` (the config file
loads), `server` (it answers `/api/snapshot`), `adapter:board` and one `adapter:<name>` per `[[runs]]` instance (it is
producing: the Board is read, the instance lists workflows and reports no error), and `gh` (installed and logged in,
which the pull request reader needs).

`skills` reads no server. The package bundles four skills: `operating-starpulse-board` (what to work next, why a task
cannot move, moving it), `authoring-starpulse-machines` (machine YAML, writers, guards, subflows, `machine validate`
and `machine import mermaid`), `writing-starpulse-adapters` (the board, machine-events and runs contracts, the adapter
kit, `emit`) and `setting-up-starpulse` (starting the server, config, `doctor`), and `skills install`
copies them to `.claude/skills` (`--claude`) or `.agents/skills` (`--codex`) in the working directory, or with `--user`
to `~/.claude/skills` or `~/.agents/skills`. An install records what it wrote, so a copy you edited afterwards is
refused (exit 1) until you pass `--force`, while one the package has since updated is replaced; `skills list` reports
which of the four each copy is.

`waiting_on` is the dependencies not yet completed. `prs` are the task's pull request links, each with the checks,
merged state and open review threads the server last read when it has them.

## Configure

`starpulse serve --config starpulse.toml` reads one TOML file; `starpulse.toml` in the working directory is read
when it exists. Database credentials never go in it: they come from the driver's environment, such as `PGPASSWORD`.

The default SQLite store must be on a local disk because WAL mode does not work on network filesystems such as NFS
or SMB. When the project or config lives on network storage, set `database_url` to a Postgres database instead.

```toml
# The tracker's web address: a task links to `<tracker_url>/tasks/<id>`. Unset, it opens in the page's own Kanban.
tracker_url = "https://tracker.example.com"

# History in Postgres instead of SQLite; install the extra with `uvx --from 'starpulse[postgres]' starpulse serve`.
database_url = "postgresql+psycopg://db.example.com/starpulse"

# The board adapter: a module under `starpulse`, or the dotted path of one an installed package provides.
# The rest of the table is that adapter's settings.
# With no [board] table the view draws its own Markdown board, `type = "native"`:
[board]
type = "native"
# path = ".starpulse/board"  # the board's directory, relative to this file; created empty when absent
# machine = "board.yaml"     # a machine file for the Board: its transitions and `writers` decide which moves are offered, and to whom

# To draw a Backlog.md project instead:
# [board]
# type = "upstream_backlog"
# path = "backlog"       # the project's backlog/ directory, relative to this file
# command = "backlog"    # the Backlog.md CLI that writes a move (`backlog task edit <id> -s <status>`)
# machine = "board.yaml" # as above

# One instance of a runs adapter, a module under `starpulse` or the dotted path of one an installed package provides
# (it offers `start(url)` and `follow(url, runs, log)`); its workflows are drawn as `<name>/<workflow>`.
[[runs]]
name = "dagu"
type = "dagu"
url = "http://dagu.example.com:8080"
run_safe = ["nightly"]                   # the workflows the page's Run now may start
domains = { Data = ["nightly", "etl"] }  # how the page groups this instance's workflows
token_env = "DAGU_INGEST_TOKEN"          # the environment variable holding the token `POST /api/runs/events` accepts for
                                         # this instance; the token never goes in this file; omit the key and the instance takes no pushed events
```

### GitHub Actions

`type = "github_actions"` reads one repository's workflows: each active workflow file is a workflow named for the file
(`ci.yml`), its jobs are the steps (waiting on their `needs`), and a job a run took once also lists its steps. A run's
`status` and `conclusion` become StarPulse's statuses (`queued`, `running`, `succeeded`, `failed`, `aborted`,
`skipped`) and GitHub's own label stays in `raw`; a label the mapping lacks is an error, never a failure.

```toml
[[runs]]
name = "gh"
type = "github_actions"
url = "https://github.com/trantor-org/starpulse"   # or `owner/name`
run_safe = ["ui-preview.yml"]
```

- **Credentials** come from the environment: `GITHUB_TOKEN` or `GH_TOKEN` (read and `actions: write` on the repository),
  and `GITHUB_API_URL` for GitHub Enterprise Server. Without a token the repository is still read, at GitHub's lower
  unauthenticated rate limit, and nothing starts.
- **Run now** dispatches the workflow on the default branch (`workflow_dispatch`) and answers its run id. It is drawn
  only on a `run_safe` workflow whose file declares `workflow_dispatch`; any other workflow is refused.
- **Events.** The repository is listed every 60 s. A `workflow_run` webhook, mapped with
  `starpulse.github_actions.workflow_run_entry` and sent to the ingest (or `starpulse emit`), reads that workflow again
  at once.

### Run a hub

`starpulse serve --hub` serves the same package from a Postgres history, for a hub that instances forward to.
Install the hub extras (`uvx --from 'starpulse[hub]' starpulse serve --hub`) and set `database_url` to a Postgres
database in the config; a config with none, or with a SQLite URL, is refused before anything starts. The hub brings
the database's schema to the latest revision on every start: the history tables are versioned with the package by
Alembic (`starpulse/migrations`, revisions recorded in `starpulse_alembic_version`), so upgrading the package and
restarting upgrades the schema. An instance without `--hub` keeps its SQLite file and never imports the hub extras.

A hub also requires an `[oidc]` table, because viewers sign in with the hub's OpenID Connect issuer before anything is
drawn; a hub without one is refused before it starts, and an instance without `--hub` refuses the table rather than
serve ungated. The hub is a confidential client of the issuer (authorization-code flow with PKCE, a state and a nonce;
ID tokens must verify against the issuer's published keys):

```toml
[oidc]
issuer = "https://id.example.com/realms/flow"          # its /.well-known/openid-configuration names the endpoints
client_id = "starpulse-hub"
client_secret_env = "STARPULSE_OIDC_SECRET"            # the environment variable holding the client secret
redirect_uri = "https://hub.example.com/auth/callback" # registered at the issuer; its /auth/callback path is fixed
allowed_groups = ["flow-viewers"]                      # an account holding none of these is refused with the reason
groups_claim = "groups"                                # optional: the ID token claim that lists an account's groups
scopes = ["openid", "profile", "email"]                # optional: add the scope your issuer needs for the groups claim
engine_token_env = "STARPULSE_ENGINE_TOKEN"            # optional: the token of an insights engine, never a viewer's
```

Before sign-in every path but `/auth/login` and `/auth/callback` answers 401, including the page, `/api/events` and every
write. Sign-in sets an `HttpOnly` session cookie that lasts eight hours; sessions live in the hub's memory, so a restart
signs everyone out. The credentials are separate: a per-instance ingest token passes only on `POST /api/runs/events`, the
engine token only on the engine's routes, and neither signs a viewer in. A new route of the server is a viewer route
until the gate says otherwise. The test suite signs in against a
[mock OIDC server](https://github.com/navikt/mock-oauth2-server) container, so it needs Docker or Podman for those cases.

#### Retention and rollups

A hub keeps its raw events (`starpulse_events`) in one partition per UTC day, keyed on the event's `at` time, and
drops whole days instead of deleting rows. An instance on SQLite is unchanged: it keeps one table and prunes by
deleting rows.

```toml
hub_retention_days = 14   # the default; a whole number of days, 1 or more
```

- **Partitions.** The hub creates today's and tomorrow's partition before it serves and again every hour, so an
  insert at midnight finds its partition already there. An event whose `at` falls on a day with no partition is refused
  by the database, so a forwarder must create that day's partition (`starpulse.hub.ensure_partitions`) or refuse
  events older than the retention bound.
- **Retention.** A day more than `hub_retention_days` before today is rolled up and then dropped (`DROP TABLE`,
  never `DELETE`), in one transaction, so a partition is never dropped without its rollup. A reader whose cursor sat
  in a dropped day finds the oldest retained event past its cursor on its next poll and records the span in
  `starpulse_gaps`.
- **Rollups.** `starpulse_day_rollups` holds one row per UTC day, team, machine and state: `entries`, how many tasks
  or runs entered the state that day; `open_entries`, how many of those had not left it when the day was rolled up;
  and `seconds`, how long the others stayed, from entering the state to the next event that moved the task or run out
  of it (which may be on a later day). The team is the entering event's `team` field, and `""` when the event names
  none. Trends older than retention read this table; anything that needs individual events is limited to the
  retained days.

### Configure a level

A hub draws one level above the Board: a flow graph over the trajectories of one Board machine, merged across
sources. It is configuration, not an org chart; the package has no pod, department or org. A `[level]` table names
what the level reads and how it is judged. An IC instance parses and checks the table but draws no level.

```toml
[level]
machine = "board"        # the Board machine whose trajectories the level reads
goal = "done"            # the terminal state the level is judged by
gates = ["review"]       # policy states every run should cross
terminals = [            # every way a run ends
  { id = "done", role = "goal" },
  { id = "archived", role = "abandoned" },
]
facets = [{ id = "source" }, { id = "type", label = "work type" }, { id = "repo" }]
title = "Flow graph"     # what the page calls the level
subject = "task"         # what one trajectory is
runs = "agent sessions"  # what is attached to a trajectory
series = "delivery"      # the card series the level opens

[level.orbit]
suns = "working"                                   # "terminal" (default) or "working"
working = ["ready", "in_progress", "review"]       # the working states drawn as suns when suns = "working"

[level.activity]
measure = "share"   # "share" (default), "count" or "flux"
pace = "min"        # "live", "min" (default, one day per minute) or "fast" (one day per ten seconds)
```

| Field | Required | Meaning |
|---|---|---|
| `machine` | yes | The Board machine the level reads. |
| `goal` | yes | The state the level is judged by; one of `terminals`. |
| `terminals` | yes | Every way a run ends, each `{ id, role }`. The role is `goal`, `abandoned` or another outcome to watch; each id is listed once. |
| `gates` | no | Policy states every run should cross. Default: none. |
| `orbit.suns` | no | What the orbit view circles: `terminal` states, or the `working` states of `orbit.working`. Default `terminal`. |
| `orbit.working` | with `suns = "working"` | The working states drawn as suns. None may be a terminal. |
| `facets` | no | The fields a viewer groups and filters by, each `{ id, label }`; the label defaults to the id. |
| `activity.measure` | no | How activity becomes dots: `share`, `count` or `flux`. Default `share`. |
| `activity.pace` | no | How fast the page replays it: `live`, `min` or `fast`. Default `min`. |
| `title` | no | The level's name on the page. Default `Flow graph`. |
| `subject` | no | What one trajectory is called. Default `task`. |
| `runs` | no | What is attached to a trajectory. Default `runs`. |
| `series` | no | The card series the level opens. Default none. |

A level that cannot be read is refused when the config loads, naming the key. Every state it names (`goal`, `gates`,
`terminals`, `orbit.working`) must be a state of `machine`: when the board is assembled, a level that names a state
its machine lacks, or a machine the board does not draw, is refused, naming it, before anything is served.

A viewer's facet filter keeps a run only when the run has a value for each selected facet and that value is selected.
A run without a value for a selected facet is excluded, never counted as zero or as an empty value; selecting nothing
keeps every run.

## Write a board adapter

A board adapter connects StarPulse to a tracker. It is a module with a `board(settings, base)` function that
returns a `starpulse.board.Board`: `settings` is the rest of the `[board]` table and `base` is the config file's
directory. The `Board` says:

- which lifecycle machines the page draws (`machines`),
- how the tracker's tasks reach the page (`start`, which feeds each task as it changes, and `keys`, the task
  keys it recognizes),
- and optionally a `writer(task, status, actor)` for moves made on the page or by an agent (each task's `moves` may
  list the `writers` the machine declares per event), an `assign` for assignee changes, a `read`, `edit` and `archive` for the full task record and guarded edits and
  archives (`edit` needs `read`; the snapshot's `capabilities` says which the board has), a `create(title, details)` that
  makes a task in the board's starting lane with the details the page filled (description, priority, labels,
  milestone, assignee, dependencies, acceptance criteria) and answers with its id (`POST /api/tasks`;
  `capabilities.create`), and its own `history`.

`starpulse.native`, the default, keeps tasks as Markdown files under `.starpulse/board/` and writes moves,
assignee changes and new tasks to them in Python, and reads a task's full record (priority, description, acceptance
criteria, plan, notes and definition of done) back for the task view; it offers no edit or archive yet. `starpulse.upstream_backlog` is the reference adapter for a tracker with its own
writer: it polls a Backlog.md project's Markdown files, puts every task in the team named by its `config.yml`'s
`project_name` (a project that sets none is refused, so no task lands in a default team), takes
the machine from the project's own statuses (any lane reaches any other, unless `machine` names a machine file
whose states are those lanes and whose `writers` reserve a move to an actor, such as `operator`), and writes moves
with the `backlog` CLI, answering a failed write with the CLI's output. An adapter with a writer subclasses
`BoardAdapterKit` with `writer` set, and the kit then checks that a move the operator may make is written and one
the machine leaves to the operator is refused to the agent. A board kit also declares `teams`, the team key the
adapter derives for each task it produces, and asserts each record carries it. Name your module in `[board] type` and StarPulse imports it.

## Public surface

What a release keeps compatible; a minor `0.y` release may break it, and its notes say so. Everything else in the package is
internal and can change in any release.

- The `starpulse` command line: its verbs, their JSON output and their exit codes.
- The documented entry point `python -m starpulse.claude_code`.
- The config file's keys and the machine YAML with its JSON Schema (`machine.schema.json`).

The modules an adapter may import, each exporting exactly the names in its `__all__`:

- `starpulse.board`: the board adapter seam (`Board`, `Written` and the writer and task protocols).
- `starpulse.board_feed`: the feed a board adapter places tasks on (`BoardFeed`) and what following a stream needs of it.
- `starpulse.contracts`: the board, machine-event and runs records, their JSON Schemas, and `RunsSink`.
- `starpulse.adapter_kit`: the test kit an adapter author runs against their adapter, and the helpers that serve it.
- `starpulse.machine_definition`: loading and validating a machine, and the `Registry` of guards and actions.
- `starpulse.snapshot`: how a machine is described to the page, and how its workflows are named.
- `starpulse.history`: the history a board adapter may keep itself, and placing a task's events on a machine.
- `starpulse.event_log`: the database event log producers append to and readers tail.
- `starpulse.config`: loading the config file, and the runs adapter a `type` names.
- `starpulse.harnesses`: loading the harness file, the tiers and efforts an agent profile names.
- `starpulse.mermaid_import`: drafting a machine definition from a Mermaid state diagram.
- `starpulse.otlp`: decoding Claude Code's OpenTelemetry log export.

A package test pins this list and each module's names, so adding or removing one is a reviewed change.

## Develop

```sh
git clone https://github.com/trantor-org/starpulse && cd starpulse
uv sync
pnpm --dir starpulse/web install && pnpm --dir starpulse/web build   # the page, built into starpulse/static
uv run starpulse serve
```

`uv run pytest` runs the suite with Python alone. When Docker or Podman is available, it also runs the Postgres-backed
integration cases; otherwise those cases are skipped. `uv sync --no-group hub` installs without the hub extras, as an IC
instance runs, and the suite then skips the Postgres and hub cases.
`pnpm --dir starpulse/web run check` typechecks, lints, tests and builds the page.
[`bench/`](bench/README.md) holds the hub-ingest and instance event-log benchmarks.

[`design/`](design/index.html) is the design mockup, a static page over a saved snapshot (`data.js`); view it with
`uv run python -m http.server 8781 --directory design`, and `uv run python -m starpulse.demo --mockup design --out
mockup.html` writes it as one scrubbed file. A pull request that changes the page (`starpulse/web/**`), the mockup or
the preview itself gets one UI-preview comment from
[`.github/workflows/ui-preview.yml`](.github/workflows/ui-preview.yml): screenshots of each changed surface's
scrubbed demo, built by [`ci/ui_preview.py`](ci/ui_preview.py) against the demo config
[`ci/preview.toml`](ci/preview.toml), with the demos published to `trantor-org/starpulse-demo` under `pr-<N>/`
while the pull request is open. The preview is review context and never gates the pull request. A push to `main`
that touches the same paths republishes both demos under `main/`, the live demo linked above.

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
