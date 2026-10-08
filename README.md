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
- **Pull requests and Copilot.** A repository's pull requests move through opened, checks passing or failing, and
  merged or closed, and GitHub Copilot's coding agent and code reviews move a pull request through their own machine.
- **History.** Every move is kept, so hovering a task traces the path it took.
- **The level above the Board.** On a hub with a `[level]` table, a Flow graph view draws each source as a planet on its own
  orbit round the level's terminal (or working) states, with comets for real arrivals; see
  [Read the level on the page](#read-the-level-on-the-page).

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
**Connect a tracker** opens a modal with one collapsible row per tracker (the native board, Backlog.md, Jira), each expanding to
numbered setup steps whose commands copy with one click (see Connect a tracker below). If the directory has a Backlog.md project (`backlog/config.yml`), serve prints one
line naming it and the `starpulse connect backlog` command that shows it instead; the page's
snapshot carries the same line as `hint`, and Connect a tracker shows it with the command as a copyable block. StarPulse keeps its event log and history in
`starpulse-history.sqlite` beside its config file, or in the working directory without one. The page has no sign-in and listens on this machine only (`127.0.0.1`): `--host 0.0.0.0` widens it to
every interface so another computer on your network can open it, which you do only on a network you trust. A write (move, edit,
start, run, history window) is refused unless it is a JSON request (`Content-Type: application/json`) that either names no
`Origin`, as a script or `curl` does, or names this server's own, so a web page on another site cannot write through your browser.

`starpulse serve --port 8800 --hours 24` changes the port and how far back a task's latest move counts toward
where it is drawn (6 hours by default). The Admin page's Server card overrides that window for everyone
viewing, and `starpulse-settings.json` beside the config keeps the override across restarts.

### Show your Claude Code sessions

Run the receiver beside the server, then start Claude Code with its log export pointed at it. The receiver publishes
through the event log of the history database the server reads, so give it the server's `--config`
(`starpulse-history.sqlite` beside that file; without one, the working directory's). Port 4318, OpenTelemetry's
default, is often taken: `--port` moves the receiver, and the endpoint below follows it.

```sh
uvx --from starpulse python -m starpulse.claude_code --config starpulse.toml --port 4319

claude --settings '{"env": {
  "CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_LOGS_EXPORTER": "otlp", "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
  "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4319", "OTEL_LOG_TOOL_DETAILS": "1",
  "OTEL_RESOURCE_ATTRIBUTES": "vcs.ref.head.name='"$(git branch --show-current)"'"}}'
```

Pass the variables through `--settings`, not the shell: an `env` block in your user-level `settings.json` overrides
`OTEL_*` variables set in the shell, so a shell export can leave a session exporting somewhere else. The session
moves the task its branch names (`TASK-<n>` in the branch), so start Claude Code on that branch.

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

An instance that only receives pushes needs no adapter: give the `[[runs]]` table a `name` and a `token_env`, and
leave out `type` and `url`. It pulls nothing, has no Run now (so no `run_safe`), and draws only what the ingest
receives from its token:

```toml
[[runs]]
name = "cron"
token_env = "CRON_INGEST_TOKEN"
```

### Work the board from an agent

```sh
starpulse board --milestone launch --label api   # tasks per column, with dependencies, pull requests and moves
starpulse task show PROJ-45                      # one task: lane, what it waits on, pull requests, moves
starpulse task moves PROJ-45                     # every column it may move to, allowed or refused to the agent
starpulse task move PROJ-45 review               # move it as the agent; a refusal is the verdict, exit 1
starpulse task trace PROJ-45 --flow in-progress  # where the task has been: Board lanes, or one machine's events
starpulse machine show in-progress               # a machine's states, transitions and the tasks now in each
starpulse milestone list                         # every open milestone: title, outcome, specs and ADRs
starpulse milestone add "Launch" --outcome "Shipped" --spec "doc-1 - plan" --adr docs/adr/a.md
starpulse doc list                               # every open doc: title, type, dates and path, without bodies
starpulse doc create "Plan" --type specification --folder specs --body "# Plan"
starpulse runs list                              # each workflow as <instance>/<workflow> with its latest status
starpulse runs start prod/nightly                # start a run-safe workflow through Run now; its run id
starpulse watch --task PROJ-45                   # one JSON line per change, until you stop it: wait without polling
starpulse analytics health --hours 72            # dwell and WIP per state, throughput and stuck tasks, with gap warnings
starpulse analytics level --hours 48             # the level's WIP, throughput, aging and per-source orbit shares
starpulse analytics trajectories --hours 48      # variants, outliers, expected days and chance of the goal, betweenness
starpulse analytics gates --task PROJ-45         # which gates a run can bypass, with the path that skips each
starpulse analytics forecast --task PROJ-45      # where a run still going is likely to end, and in how many days
starpulse analytics what-if --from review --to in_progress --p 0.1  # the change in the goal and days
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
| `snapshot` | | the server's snapshot: `graphs`, `flows`, `dags`, `pools`, `pulls`, `claims`, `insights`, `settled`, ...; each `flows` entry but the Board's also carries `ties` (`{kind, machine, state, count, dag, when}`: `declared`, `observed` or `dag`), `parent`, `depth`, `chain`, `nested`, `last` and `stuck` (`{machine, state, since}`, a task idle over 2 h), rolled up from the machines nested below it; `machinePage` and `machineStrip` page and count the machines entered from the In Progress one (Machine rows) |
| `board` | `--state`, `--milestone`, `--label`, `--assignee` | `columns`: each `{state, name, tasks}`; a task is `{id, title, lane, assignee, milestone, labels, dependencies, waiting_on, prs, moves}` |
| `task show` | `TASK` | a task as above, with its `description`; a completed or archived task has only its `id` and where it settled as `lane` |
| `task moves` | `TASK` | `task`, `lane` and `moves`: each column the task may move to as `{allowed, reason, skill}`, as the agent meets it |
| `task move` | `TASK`, `TO`, `--session` | `ok`, `task`, `to`, `reason`, `skill` and `advice`: the move made, or the refusal and the skill that satisfies it (exit 1); exit 3 when the board has no writer |
| `task trace` | `TASK`, `--flow` | `task`, `flow` (null without `--flow`), `path` and `steps`; the Board's `{at, from, to}` lane changes, or with `--flow` that machine's `{at, event, state}`, oldest first; an unknown flow exits 4, a task never seen has an empty `path` |
| `machine list` | | `machines`: each `{name, states, tasks}` with its state ids and its live task count |
| `machine show` | `NAME` | `name`, `states` (each `{id, name, initial, final, count, tasks}`) and `transitions`; an unknown machine exits 4 and names those drawn |
| `machine validate` | `PATH...` | `ok` and `machines`: each `{path, ok, errors}`, an error `{file, line, message}` (`line` is null when the compiler cannot place it); exit 1 when any file is refused. A guard or action name is taken as the adapter's to register |
| `machine import mermaid` | `SOURCE`, `--out` | `written`: the new file, by default `.starpulse/machines/<name>.yaml`; an existing file is refused (exit 1), a missing source is exit 4 |
| `milestone list` | `--json` | `milestones`: each open milestone as `{id, title, outcome, specs, adrs, retro, description}`, by ascending number; `--json` is accepted and changes nothing, since every verb prints JSON; a board that keeps no milestones exits 3 |
| `milestone show` | `MILESTONE` | one milestone's record as above; one that is not open exits 4 |
| `milestone add` | `TITLE`, `--outcome`, `--spec`, `--adr`, `--retro` | `milestone`: the new id (the next number past every open and archived milestone); `--spec` and `--adr` repeat; a blank title exits 1 |
| `milestone edit` | `MILESTONE`, `--title`, `--outcome`, `--spec`, `--adr`, `--retro` | `milestone` and `changed`, the fields whose value differs; `--spec` or `--adr` given at all replaces that whole list, and a change that changes nothing writes nothing; naming no field exits 2, a refused change exits 1, an unknown milestone exits 4 |
| `milestone archive` | `MILESTONE` | `milestone`: moves the file to `archive/milestones/`; refusals as `milestone edit` |
| `doc list` | `--json` | `docs`: each open doc as `{id, title, type, created_date, updated_date, path}` with `path` relative to the board's `docs/`, by ascending number and without its body; `--json` is accepted and changes nothing, since every verb prints JSON; a board that keeps no docs exits 3 |
| `doc show` | `DOC`, `--json` | one doc's record as above plus its `body`, the text after its front matter; one that is not open exits 4 |
| `doc create` | `TITLE`, `--type`, `--folder`, `--body` | `doc`: the new id (the next number past every open and archived doc); `--type` is `specification`, `guide`, `readme` or `other` (the default), `--folder` a folder of plain names under `docs/` such as `specs`; a blank title, an unknown type or a folder that leaves `docs/` exits 1 |
| `doc update` | `DOC`, `--title`, `--type`, `--body` | `doc` and `changed`, the fields whose value differs; a change that changes nothing writes nothing, naming no field exits 2, a refused change exits 1, an unknown doc exits 4 |
| `doc archive` | `DOC` | `doc`: moves the file to `archive/docs/`; refusals as `doc update` |
| `runs list` | | `runs`: each workflow as `{workflow, status, raw, run_id, started_at, finished_at}` with `workflow` `<instance>/<workflow>`, and `error`, the runs adapters' error or null |
| `runs start` | `WORKFLOW` | `workflow` and `run_id`: starts `<instance>/<workflow>` through the server's Run now path, so only a workflow in the instance's `run_safe` starts and only from the loopback or private network, as JSON with no foreign `Origin` (exit 1 when refused); an instance with no start exits 3, a workflow outside `run_safe` exits 4 |
| `watch` | `--machine`, `--task` | one line per change after the connect snapshot, `{event, data}` with `event` `task`, `move`, `pulls`, `claim` or `dags` and `data` the server's delta; `--machine` keeps that machine's changes (`board` takes `task`, `pulls` and `claim`), `--task` that task's, and either drops `dags`; an unknown machine exits 4, the server ending the stream exits 3, and an interrupt exits 0 |
| `analytics health` | `--hours`, `--stuck-hours` | `now`, `window_s`, `stuck_after_s`, `states`, `throughput`, `stuck` and `warnings`, below |
| `analytics level` | `--hours` | `now`, `window_s`, `history_s`, `machine`, `goal`, `wip`, `throughput`, `time_in_state`, `aging`, `orbit` and `sources`, below; a window longer than the history exits 1 and a server with no level exits 3 |
| `analytics trajectories` | `--hours` | `now`, `window_s`, `history_s`, `machine`, `goal`, `ended`, `variants`, `norm`, `outliers`, `chain`, `betweenness`, `bottleneck`, `loops` and `runs` (each `{source, task, path, back_edges, sccs, loops}`), below; refusals as `analytics level` |
| `analytics gates` | `--hours`, `--task` | `now`, `window_s`, `history_s`, `machine`, `goal`, `ended`, `gates` and `runs`, below; `--task` keeps one run and exits 4 when it ended nowhere in the window; refusals as `analytics level` |
| `analytics forecast` | `--hours`, `--task` | `now`, `window_s`, `history_s`, `machine`, `goal`, `ended`, `forecast` and `calibration`, below; `--task` keeps one run and exits 4 when it has no run still going; refusals as `analytics level` |
| `analytics what-if` | `--from`, `--to`, `--p`, `--hours` | `now`, `window_s`, `history_s`, `machine`, `goal`, `ended`, `from`, `to`, `p`, `was`, `n`, `start`, `p_goal`, `expected_days` and `chain`, below; a what-if the chain cannot answer exits 1; refusals as `analytics level` |
| `config check` | `--config` | `ok`, `file`, `unknown_keys`, `errors` and `config`, the effective config with every default filled in (null when it does not load); exit 1 when it does not load |
| `demo` | `--out`, `--mockup`, `--server` | `written`: the HTML file; it reads the server's snapshot, or a design mockup directory with `--mockup` |
| `doctor` | `--config` | `ok` and `checks`: each `{check, status, reason}`, `status` `pass`, `warn` or `fail`; exit 1 when any fails, never for a warning |
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
does not list every task's lane changes through `lane_rows(since=None)` and `gaps()`; `since`
is an epoch the Ledger passes so it reads only its last 24 hours, and None asks for every change.

`analytics level` reads `GET /api/level[?hours=N]` (a window of 168 hours by default), served by a hub (`serve --hub`)
whose config has a `[level]` table. It counts the level's machine on the Backlog flow metric definitions, merged across
the sources that forward to the hub, a source being the prefix of an event id (`<source>/<id>`; `unattributed` when
none). `wip` is the runs now in a working state (`orbit.working`, else every state that is neither initial nor a
terminal), `throughput` the entries into the goal in the window, `time_in_state` each non-final state's stays clipped
to the window, and `aging` each working run's age since its current working interval began against `threshold_s`, the
85th-percentile cycle time of the trailing 12 weeks (null with no completion to measure). `orbit` totals the ended runs
per terminal and the working time per working state, and each of `sources` carries its `ended` runs with
`terminal_share`, its `dwell` per working state with `time_share`; a set of shares sums to 1, and is empty, not zero,
for a source with nothing ended or worked. `level` echoes the config the page draws from (`title`, `subject`, `runs`,
`gates`, `terminals` with their roles, `orbit.suns` and `orbit.working`, `facets`, `activity.measure` and
`activity.pace`), each source's `shared` is whether it has a Board of its own (false for `unattributed`), and
`arrivals` lists each run's entry into a terminal inside the window as `{source, state, at}` (epoch seconds, oldest
first), the comets the page replays. History begins at the first event the hub holds: a window longer than it is
refused (exit 1, the error naming the history's hours, `history_s` in the HTTP body), never padded with zero days. A
server with no level is 404 (exit 3).

`analytics trajectories` and `analytics gates` read `GET /api/level/trajectories[?hours=N]`, with the window, history and
refusals of `analytics level`. They cover the runs of the level's machine that ended in a terminal inside the window,
each a whole path with its self-loops collapsed. `variants` counts each distinct path (`{path, count, share}`, most
common first) and `norm` is the most common; `outliers` ranks the other runs by Levenshtein distance from the norm,
furthest first. `chain` is an absorbing Markov chain over the observed transitions, terminals absorbing: per state
`expected_days` to finish and `p_goal`, solved from the fundamental matrix N = (I - Q)^-1 with N times the mean stay
and N times the chance of stepping into the goal. `betweenness` is Brandes centrality per state on the transition
graph and `bottleneck` the state holding the most path time, `{state, path_days}`. `loops` is the rework: each back-edge
(`from`, `to`) some run took, with the `runs` that took it and the `trips` and `days` summed over them, the longest first. A
run's own `back_edges` and `sccs` count the back-edges of a depth-first search from its first state and the strongly
connected components of two states or more in the graph of its own steps; its `loops` list each back-edge with its
`trips` and the `days` they took, from the target's previous visit to each return; the step that first enters a state is no
trip, so a back-edge no run went round again is not listed. They come from each run's own graph and
never the union of every run's, so a cycle only two runs together close is not reported. `gates` has one entry per
configured gate over the runs that reached the goal: how many `crossed` it, how many had to cross it (`mandatory`),
`bypassed`, `bypassable`, and a `witness` `{task, path}`, the shortest path a bypassing run could have taken to the
goal without the gate. Dominators are computed per run, on the graph of that run's own steps (`runs`: each
`{source, task, path, reached_goal, gates}` with each gate's `crossed`, `mandatory`, `dominators` (the states every
path from the run's first state to the gate crosses), `post_dominators` (every path from the gate to the goal) and
`witness`), never on the union of every run's graph, which holds paths no run took. A gate a run visited only on a
detour is bypassable. A trajectory joined with its agent sessions is not computed here: the history keeps task steps,
not sessions.

`analytics forecast` reads the same route's `forecast` and `calibration`. `forecast` is each run still going (its last
state neither a terminal nor final), by task: `{source, task, state, loops, since, p, p_goal, expected_days, n,
pooled}`. `loops` is the rework loops it has gone round so far, the trips of the back-edges of its steps up to now, and
the chain the forecast reads is fitted on the ended runs with each state split by that count, two and more sharing a row,
so a third review round is not read as the first. `p` is the chance of ending in each terminal and `expected_days` the
days to finish, from the row's N = (I - Q)^-1; `n` is how many times the ended runs left that row. A row left fewer than
5 times is `pooled`: the state's own row, whatever the loop count, answers; a state no ended run left has null chances
and `n` 0. It is a probability with its sample size, never a status. `calibration` scores the forecast: the latest fifth
of the ended runs by when they ended are held out (`held_out`, the rest being `fit`), each of their steps before the end
is forecast from a chain fitted on the others, and `deciles` bins those `predictions` by forecast chance of the goal,
each `{low, high, n, runs, predicted, observed}` with `predicted` the mean forecast and `observed` the share of the
goal reached; `calibrated` is whether every decile holding a forecast is within 10 points, null with none.

`analytics what-if` reads `GET /api/level/what-if?from=&to=&p=[&hours=N]`: the chain of the runs that ended in the
window with `from -> to` at probability `p` (`was` the observed one over `n` exits), `from`'s other exits keeping their
shares of the rest. `p_goal` and `expected_days` are `{before, after, change}` from `start`, the state most ended runs
began in, and `chain` is the changed chain per state. A state no ended run left (a terminal `to` needs none), `to` the
same as `from`, a `p` outside 0 to 1, a transition that is its state's only exit, or a chain that would never finish is
400 (exit 1).

A move carries the actor that makes it. The machine YAML names, per event, who fires it (`writers`), and each move
the server offers lists them as `writers`; `POST /api/move` takes `{task, to, actor}` with `actor` `operator` when
absent, which is what the page sends. The server refuses an actor outside the event's writers before the board
writer is asked, so a move declared for `operator` alone (sending an In Progress task back to Ready) is refused to
`starpulse task move`, which always moves as `agent`. A board adapter's `writer` receives that actor as its third
argument: `writer(task, status, actor)`. `/api/move` is unauthenticated on the LAN, so this stops an agent's
accident, not an adversary.

The same file names, in a `cues:` block, the workflows an event cues: each entry is `{event, dag, on, resolves}`, with
`dag` as `<instance>/<workflow>`, `on` the occasion the page shows (`push to main`) and `resolves` either `forced` (a
failed run stays pinned until a forced rerun) or `next` (it clears on the DAG's next run). The cued event must reach
exactly one state, beside which the page draws the cue; a file with no block has no cues.

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

Two contract checks read the config against the machines' cues. `cue:<instance>/<workflow>` runs once per cued
workflow: it fails when no instance lists the workflow or when a `[runs.commit]` key (`after`, `before`, `force`,
`task`) names a parameter the workflow does not declare (read from Dagu's `dag.params`), and it warns, without failing
the run, when the instance has no `after` key, so its runs pair with a merge only by the time they started.
`repo:<name>` runs once per `[[repos]]` entry and fails when its `path` is not a submodule of the repository `doctor`
runs in. Neither runs while the config or the server cannot be read.

`GET /api/doctor` serves those two kinds of check as `{ok, checks: [{check, status, reason}]}`, read from the server's
own snapshot and config and held for a minute; the page draws it as the Ledger's doctor banner. A server with no
contract to read answers `{ok: true, checks: []}`.

`skills` reads no server. The package bundles four skills: `operating-starpulse-board` (what to work next, why a task
cannot move, moving it), `authoring-starpulse-machines` (machine YAML, writers, guards, subflows, `machine validate`
and `machine import mermaid`), `writing-starpulse-adapters` (the board, machine-events and runs contracts, the adapter
kit, `emit`) and `setting-up-starpulse` (starting the server, config, `doctor`), and `skills install`
copies them to `.claude/skills` (`--claude`) or `.agents/skills` (`--codex`) in the working directory, or with `--user`
to `~/.claude/skills` or `~/.agents/skills`. An install records what it wrote, so a copy you edited afterwards is
refused (exit 1) until you pass `--force`, while one the package has since updated is replaced; `skills list` reports
which of the four each copy is.

#### The pull-request store

With `gh` available, `serve` keeps a store of pull requests (table `starpulse_pull_requests`) and refreshes it every
minute, one GraphQL query per repository: every open pull request, plus any other pull request updated since the newest
`updatedAt` the store holds for that repository. A merged or closed record is final and is never read again. An open
pull request is re-read on every refresh even when its `updatedAt` is unchanged, because a check finishing does not
bump it. A pull request the store has not seen yet costs one follow-up query, so a cold store costs two. The
repositories are those of open tasks' pull request links, the `[[repos]]` entries under a linked owner, and those
already stored. Each query's `rateLimit` cost is logged (`pull requests: <repo> query cost N, remaining N, resets T`).
A repository with more than 100 open pull requests is read for the first 100, with a warning.

`GET /api/pulls[?repo=owner/name][&number=N][&state=OPEN|MERGED|CLOSED][&body_contains=text]` serves the store,
`{pulls: [...]}`, ordered by repository then number. Each record holds `repo`, `number`, `state`, `isDraft`,
`mergeable`, `baseRefName`, `headRefOid`, `body`, `checks` (`pass`, `failing`, `pending` or `none`), `requiredChecks`
(`{name, result}`), `threads` (open review threads), `updatedAt` and `fetchedAt` (epoch seconds of the read). A `number` that is not an
integer or an unknown `state` answers 400.

`waiting_on` is the dependencies not yet completed. `prs` are the task's pull request links, each with the checks,
merged state, open review threads and commits behind `main` the server last read when it has them.

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

# How long `serve` keeps the event log's rows: it prunes older ones at start and hourly, so the table, a SQLite file
# and every reader's replay at boot stay bounded. A reader that was down longer than this resumes at the oldest kept
# row and records the span it missed in `starpulse_gaps`. A whole number of days, 1 or more.
event_log_retention_days = 7   # the default

# Where `serve` writes each row it prunes, before it deletes the row (see Event log archive): a directory, relative to
# this file unless absolute. A `serve --hub` prunes no rows and writes no archive.
event_log_archive_dir = "starpulse-archive"   # the default

# The board adapter: a module under `starpulse`, or the dotted path of one an installed package provides.
# The rest of the table is that adapter's settings.
# With no [board] table the view draws its own Markdown board, `type = "native"`:
[board]
type = "native"
# path = ".starpulse/board"  # the board's directory, relative to this file; created empty when absent
# machine = "board.yaml"     # a machine file for the Board: its transitions and `writers` decide which moves are offered, and to whom
# criteria = "my-evaluator {id}"  # evaluates a task's Start Criteria; {id} is the task's id (see below)

# To draw a Backlog.md project instead:
# [board]
# type = "upstream_backlog"
# path = "backlog"       # the project's backlog/ directory, relative to this file
# command = "backlog"    # the upstream Backlog.md CLI (`npm i -g backlog.md`) that writes a move (`backlog task edit <id> -s <status>`); a fork of it that lacks `backlog init` is not it
# machine = "board.yaml" # as above

# To draw a Jira project instead (read-only; building the board reads the site once, to import the workflow):
# [board]
# type = "jira"
# url = "https://example.atlassian.net"  # the site, http or https
# project = "PAY"                        # the Jira project key, which is each task's team
# workflow = "Payments Software Workflow" # the Jira workflow imported as the Board machine
# token_env = "JIRA_TOKEN"               # the environment variable holding the token: Bearer, or with `user` the Basic password
# user = "ada@example.com"               # Jira Cloud: the account the API token belongs to
# interval = 30                          # seconds between polls

# Draw each task's pull-request CI as a sub-flow of these Board states: StarPulse ships one `ci` machine, which GitHub
# moves and StarPulse only observes (its `source` is GitHub). Each name is a Board state id; one the Board lacks is refused.
# With `gh` available, each task with a PR is one agent in that flow, and its trail is the PR's pushes, check results,
# re-runs, conflicts, rebases and merge, read from GitHub every minute and kept in the event log (`machine:events`).
# [ci]
# states = ["in_progress", "review"]

# One instance of a runs adapter, a module under `starpulse` or the dotted path of one an installed package provides
# (it offers `start(url)` and `follow(url, runs, log)`, and optionally `rerun(url)` and `declared_params(url, workflow)`, the parameter names a workflow declares, which `doctor` reads); its workflows are drawn as `<name>/<workflow>`.
[[runs]]
name = "dagu"
type = "dagu"
url = "http://dagu.example.com:8080"
run_safe = ["nightly"]                   # the workflows the page's Run now may start
domains = { Data = ["nightly", "etl"] }  # how the page groups this instance's workflows
token_env = "DAGU_INGEST_TOKEN"          # the environment variable holding the token `POST /api/runs/events` accepts for
                                         # this instance; the token never goes in this file; omit the key and the instance takes no pushed events
                                         # an instance with `token_env` and neither `type` nor `url` is push-only (see above)

# Optional: the run parameters that carry what a run applies, so the Ledger pairs a run with its merge for certain.
# Each value names a parameter; a key left out is a parameter this instance has none of.
[runs.commit]
after = "AFTER"                          # the merge commit the run applies: pairs the run with that merge
before = "BEFORE"                        # the commit before it
force = "FORCE"                          # the parameter that marks a forced run
task = "TASK"                            # the task a run is for: pairs a run with a task's entry into a lane (any Board event but MERGED)

# Optional: a repository whose merges apply through the parent's pin bump rather than a run of their own. `name` is the
# repository as its pull request links spell it, `path` where the parent holds it as a submodule.
[[repos]]
name = "skills"
path = "skills"
applied_by = "pin-bump"
```

#### Event log archive

Before `serve` deletes an event-log row it appends the row to a gzip JSONL file under `event_log_archive_dir`, one
file per UTC day of the row's `at`, named `YYYY-MM-DD.jsonl.gz`. A later pass that prunes more of a day appends to that
day's file, which is then several gzip members in a row; `gzip` and DuckDB read them as one stream. A pass writes and
fsyncs a batch of rows, 1000 at most, before it deletes that batch, so a write that fails (disk full, directory not
writable) deletes nothing and logs the failure, and the next hourly pass retries. A crash between the write and the
delete archives those rows again, so a reader of the archive keys a row on `id`.

Each line is one JSON object with every column of `starpulse_events`:

```json
{"id":1,"stream":"machine:events","event_id":"evt-1","fields":{"machine":"m","event":"A"},"at":1788307200.5}
```

`at` is seconds since the epoch. Read a day with DuckDB, or with the standard library:

```sql
SELECT id, stream, event_id, fields, to_timestamp("at") AS at FROM read_json('starpulse-archive/*.jsonl.gz');
```

```python
import gzip, json

with gzip.open("starpulse-archive/2026-09-01.jsonl.gz", "rt") as lines:
    rows = [json.loads(line) for line in lines]
```

#### The Ledger

A Board event a machine's `cues` name or that a workflow writes (`writers`) is *tied* to that workflow. The snapshot's
`ledgers` (and the `ledgers` event after it) list, per tied event, each occurrence newest first with the run of every
tied workflow that answered it: `{key, at, tasks, runs}`, and for the `MERGED` event `sha` and `pr` (`{repo, number, url}`)
too. A run is `{runId, status, startedAt, finishedAt, steps, step, inferred, ambiguous}`: its status, its status per
step, and the step it is in.

- `MERGED` occurrences are merged pull requests, which carry their tasks, from the last day. Any other event's are tasks
  entering the lane the event reaches within the last day.
- The snapshot's `ledgers.MERGED` holds only the newest 20 merges (a page); `GET /api/merges?before=<at>&limit=20` returns
  the next older page as `{merges, more}`, `before` being the `at` of the last row held. Rows sharing the boundary second
  come together, so a page can run past `limit` and walking it neither repeats nor skips a merge; none is older than 24
  hours. `mergeStrip` (snapshot, and with `ledgers` in the `ledgers` event; null with no workflow tied to `MERGED`)
  counts the whole day without the rows: `{since, bucket, buckets}`, 96 buckets of 900 seconds from `since`, each
  `{merges, failed, reruns}`: merges landed, those holding a failed run, and forced reruns started (a run whose
  `[runs.commit]` `force` parameter is set and not `0` or `false`). `mergePins` (same two carriers) lists the pinned
  merges of the last day that the newest page leaves out, so a failure waiting on its cue is never paged out of sight.
- A run whose parameters name an occurrence under `[runs.commit]` (`after` for a merge's commit, a full or abbreviated
  sha; `task` for a task) pairs with it and is not `inferred`. A run that names an occurrence StarPulse does not hold pairs
  with nothing.
- Any other run of a tied workflow pairs with the newest occurrence before it started and is `inferred`; its `ambiguous`
  counts the older occurrences that landed since the workflow's previous run, any of which it may equally be for. Of several
  inferred runs for one occurrence the earliest wins, and a keyed run outranks them.
- A workflow's `recent` runs (`Dag.recent`, the last day's, with their parameters) are read from Dagu for tied workflows
  only, and are left out of the `dags` the page draws.
- A failed run of a cued workflow *pins* its occurrence: the row carries `fails` (`{<instance>/<workflow>: {runId, step,
  startedAt, finishedAt, resolves, resolved}}`) and `pinned` while any failure is open. The cue's `resolves` decides the
  clearing run, which must have started after the failure and succeeded: `next`, any such run of that workflow; `forced`,
  one whose `[runs.commit]` `force` parameter is set (not empty, `0` or `false`) and which covers the failure, naming no
  commit or task or an occurrence at least as new (a commit the Ledger does not hold covers nothing). A failure is
  tracked apart from the run drawn for the occurrence, so a green plain retry of the same commit does not clear a
  forced failure. A cue with no `resolves` rule, or an event no cue names, takes `next`. An instance with no `force`
  key never clears a forced failure.
- `POST /api/runs/<instance>/<workflow>/rerun` starts a run-safe workflow with `force` set to `1` and the `after`,
  `before` and `task` parameters of its newest open failure, through the runs adapter's optional `rerun(url)` (the
  Dagu adapter offers it). It answers `{runId}`; 409 when the instance declares no `force` or the workflow has no open
  failure; 404 for a workflow outside `run_safe`; 403 off the LAN. A GET answers 405.
- A pin lasts as long as StarPulse can still read the failed run: the last day of Dagu runs (`recent`) and the window of
  merged pull requests and lane entries. An older failure drops out of the Ledger and cannot be rerun here.
- A `[[repos]]` entry names a repository whose merges apply through the parent's pin bump. Its `MERGED` rows take no run
  and carry `appliedBy`: the `key` of the first later merge in another repository whose submodule pointer at `path`
  contains the merge's commit (read through `gh`), or `null` while no such merge exists. That merge's row lists what it
  applies in `applies`. A pin bump appears only when a task cites its pull request.

#### Machine rows

The machines entered from an open machine (the In Progress one at the top) are its rows, newest activity first: a row is
as recent as the newest task of the machine and every machine nested below it, ties break by name, and a machine with no
task comes last. The snapshot's `flows` carries every machine; `machinePage` (`{open, machines, more}`) names the In
Progress machine's first 20 rows. `GET /api/machines?open=<machine>&before=<last>&limit=20` returns the next page of any
level as `{open, machines, more}`, each machine whole as a `flows` entry with its derivation. `open` defaults to the In
Progress machine, `before` is the `last` of the last row held (0 for a machine with no task), and `limit` runs 1 to 100.
Rows sharing the boundary activity come together, so a page can run past `limit` and walking it neither repeats nor skips
a machine. An unknown `open` is 404; a `before` that is not a finite number or a `limit` out of range is 400.

`machineStrip` (`{entries}`) lists every machine entry of the 24 hours before the snapshot's `now`, without the rows, oldest first, as
`{at, machine, row, from, dag}`: `row` is the machine on the In Progress level the entry lands on, so an entry into a
nested machine counts on the row above it; `from` is the `{machine, state}` the task's session was entered from (null
when no earlier session is known); `dag` is the workflow that launched a session with no task.

The page scrolls the rows under the fixed top by the wheel, Page Up and Page Down, the arrow keys, Home and End and a
draggable thumb, with `↑ back to newest` once scrolled; the rows are drawn only while in view. As the footer comes
into view it loads the next 20 older machines from `/api/machines`. The 24 h strip under the rows draws a tick per
entry, coloured by the state it was entered from (amber for a workflow launch), shades the rows in view as one
stretch, and a click on a tick scrolls to its row. A click on a state of the top scrolls to the first machine it
opens and picks it out; Escape steps back from the card, then the picked row, then the scroll to newest. A click on a task pins it and narrows the rows and the strip to
the machines it holds a session in (`N machines holding <task>`); closing its card restores every row. A demo page (`?demo`) takes `&many=N` to grow the machines under
the In Progress one to N, enough to scroll.

### Connect a tracker

`starpulse connect` checks that a tracker answers, then writes the `[board]` table of `starpulse.toml` for you, keeping
every other table and comment. It prints one line saying what it read. A tracker that does not answer writes nothing,
says why on stderr and exits 1; `--config` names another file, and `starpulse connect <tracker> --help` lists each
tracker's flags.

```sh
starpulse connect native --path .starpulse/board --machine board.yaml   # StarPulse's own board; --path and --machine are optional
starpulse connect backlog --path backlog                                # a Backlog.md project; --command names its CLI
# ✓ Read 36 tasks in 5 lanes from backlog/ · wrote [board] to starpulse.toml

export JIRA_TOKEN=<your API token>   # read from the environment, never an argument and never written to the file
starpulse connect jira --url https://acme.atlassian.net --project PAY --workflow "Payments Software Workflow" --user ada@example.com
# ✓ Imported Payments Software Workflow (7 states) · read 42 issues from PAY · wrote [board] to starpulse.toml
```

### GitHub Actions

`type = "github_actions"` reads one repository's workflows: each active workflow file is a workflow named for the file
(`ci.yml`), its jobs are the steps (waiting on their `needs`), and a job a run took once also lists its steps. A run's
`status` and `conclusion` become StarPulse's statuses (`queued`, `running`, `succeeded`, `failed`, `aborted`,
`skipped`) and GitHub's own label stays in `raw`; a label the mapping lacks is an error, never a failure. A
GitHub-managed dynamic workflow (`dynamic/dependabot/update-graph`) has a path that is no file: it is listed from its
latest run's jobs alone and cannot be started.

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
  `starpulse.adapters.runs.github_actions.workflow_run_entry` and sent to the ingest (or `starpulse emit`), reads that workflow again
  at once.

### Show pull requests and Copilot work

`python -m starpulse.adapters.runs.github` reads a repository's 30 most recently updated pull requests every `--interval` seconds
(300 by default) and appends their events to the event log, beside the server:

```sh
uvx --from starpulse python -m starpulse.adapters.runs.github --repo trantor-org/starpulse
```

- **`github-pull-request` machine.** `PR_OPENED`, then `CHECKS_PASSED` or `CHECKS_FAILED` once every check run on the
  head commit has completed, then `PR_MERGED` or `PR_CLOSED`.
- **`copilot` machine.** `WORK_STARTED` and `WORK_FINISHED` from the `copilot_work_started` and `copilot_work_finished`
  timeline events (the actor is the person who asked), `RUN_STARTED` and `RUN_FINISHED` from the `dynamic` workflow run
  "Running Copilot cloud agent", `REVIEW_RUN_STARTED` and `REVIEW_RUN_FINISHED` from "Running Copilot Code Review", and
  `REVIEW_SUBMITTED` from a review by `copilot-pull-request-reviewer[bot]`. GitHub exposes no per-tool trajectory for
  these sessions, so Copilot gives spans and outcomes, not trajectories. GitHub documents neither timeline event name;
  the adapter's tests pin them on recorded responses.
- **Keys.** An event is keyed by the task the pull request's branch names (`--key`, `--branch` and `--key-format`, as
  for the Claude Code receiver), else by the pull request as a run (`owner/name#7`).
- **Credentials** are `GITHUB_TOKEN` or `GH_TOKEN` (read access to pull requests, checks and Actions), and
  `GITHUB_API_URL` for GitHub Enterprise Server. A re-read appends nothing already in the log.

The two machine definitions ship in the package under `starpulse/machines/`.

### Run a hub

`starpulse serve --hub` serves the same package from a Postgres history, for a hub that instances forward to.
Install the hub extras (`uvx --from 'starpulse[hub]' starpulse serve --hub`) and set `database_url` to a Postgres
database in the config; a config with none, or with a SQLite URL, is refused before anything starts. The hub brings
the database's schema to the latest revision on every start: the history tables are versioned with the package by
Alembic (`starpulse/store/migrations`, revisions recorded in `starpulse_alembic_version`), so upgrading the package and
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
signs everyone out. The credentials are separate: a per-instance token passes only on `POST /api/runs/events` and `POST /api/forward`, the
engine token only on the engine's routes, and neither signs a viewer in. A new route of the server is a viewer route
until the gate says otherwise. The test suite signs in against a
[mock OIDC server](https://github.com/navikt/mock-oauth2-server) container, so it needs Docker or Podman for those cases.

#### Retention and rollups

A hub keeps its raw events (`starpulse_events`) in one partition per UTC day, keyed on the event's `at` time, and
drops whole days instead of deleting rows, so it starts no row prune and writes no event log archive. An instance on
SQLite is unchanged: it keeps one table and prunes by deleting rows, archiving each first.

```toml
hub_retention_days = 14   # the default; a whole number of days, 1 or more
```

- **Partitions.** The hub creates today's and tomorrow's partition before it serves and again every hour, so an
  insert at midnight finds its partition already there. An event whose `at` falls on a day with no partition is refused
  by the database, so a forwarder must create that day's partition (`starpulse.api.hub.ensure_partitions`) or refuse
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

### Post findings from an engine

A hub with `engine_token_env` set takes findings from an external engine: a separate package that reads the hub's
history and says what it found. This package holds no engine code; the insights API is the fourth contract beside the
board, machine-event and runs records, and its record is `Finding` (`starpulse/schemas/insights.schema.json`):

```sh
curl -X POST https://hub.example.com/api/insights -H "Authorization: Bearer $STARPULSE_ENGINE_TOKEN" -d '{
  "id": "slow-review",
  "engine": {"name": "skill-coach", "version": "1.4.0"},
  "scope": {"team": "platform", "state": "review"},
  "severity": "warn",
  "text": "Review takes four times as long as the norm.",
  "evidence": [{"label": "time in review", "url": "https://hub.example.com/history?state=review"}],
  "created_at": 1700000000
}'
curl -X DELETE https://hub.example.com/api/insights/slow-review -H "Authorization: Bearer $STARPULSE_ENGINE_TOKEN"
```

- **Fields.** `id` names the finding, `engine` the `name` and `version` that made it, `severity` is `info`, `warn` or
  `act`, `text` is at most 280 characters, and `created_at` and the optional `expires_at` are epoch seconds. `evidence`
  lists labelled links, each exactly one of a `url` or a history `query`. `scope` may name a `team`, `machine`, `state`
  and `task`, all optional. The contract has no field for a person, and a body with an unknown field, a scope that
  names an assignee or a user included, is refused: a finding is about work, never about someone.
- **Answers.** A new id answers 201 `{id, replaced: false}`. A re-post of an id replaces its finding and answers 200
  `{id, replaced: true}`. A body the contract refuses answers 400 naming the field to fix, one over 64 KiB 413, and a
  history store that refuses the write 503; none of them writes or sends anything. `DELETE /api/insights/<id>` retracts
  a finding (200 `{id, retracted: true}`), and an id that is unknown or already retracted answers 404.
- **Credentials.** Only the engine token reaches these routes, and no viewer's session or forwarder's token does. A hub
  without `engine_token_env`, and an instance without `--hub`, has no insights routes and answers 404.
- **History and stream.** Findings are kept in `starpulse_insights`, a retracted one with its `retracted_at`. The
  stream sends an `insight` event `{id, finding}` for each post and re-post and `{id, finding: null}` for a retraction,
  and the snapshot's `insights` lists the findings neither retracted nor past their `expires_at`, so a client that
  connects later reads them, as does a hub that restarts. The page draws none of them.

An engine author tests against the real routes with `InsightsEngineKit` from `starpulse.adapter_kit`: override
`produce()` to return the engine's findings as plain dicts, and the kit checks each against the contract and schema,
posts, re-posts and retracts each through a served stack and asserts the stream sends every state, and asserts a
finding scoped to a person is refused.

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

### Read the level on the page

A hub with a `[level]` table adds a **Flow graph** view to the page (`?view=graph`), the level above the Board, drawn from
`GET /api/level` alone: it reads only the `level` echo above, never a name from the page's own build. Each source is a
planet on a closed orbit; the orbit has one petal per sun, and the planet spends a share of each period in a petal
that grows with the source's share of that sun (never zero, so the planet's speed at the centre crossing differs
between petals by under four times). A sun is a terminal state sized by the runs that ended there, or with
`orbit.suns = "working"` a working state sized by the task-days spent there, the terminals standing in a column to its
right. At rest the view names each body and moves only the planets, each with a short tail, and the comets: a comet falls
into a terminal for each batch of arrivals (`activity.measure`: `share` and `flux` batch by a tenth of the source's WIP,
`count` by five), replayed at `activity.pace`: `live` follows real time with no loop, `min` replays a day a minute and
`fast` a day in ten seconds, both looping the window. The numbers are on demand: hovering a source rings it with where
its runs end and traces it to each sun, hovering a sun traces each source to it, and either opens a tip with the shares,
counts and the source's bottleneck state. A click focuses a body and Tab steps through them, the sources and then the
suns, leaving the card past the last: a steady ring follows the focused body while the replay keeps it moving, its
traces stay lit, and a details panel docks at the card's right edge (`src/features/orbit/orbitDetails.ts`). For a source it gives the
open and ended runs, each terminal's count and share, and the drift, then the time in each state (share, stays, mean
stay), the open runs oldest first with those past `aging.threshold_s` flagged, and the latest arrivals. For a terminal
sun it gives the runs that ended there, their share of every end and the last day's count, then each source's count and
the latest arrivals; for a working sun, the open runs, task-days and stays, then each source's time there and the open
runs in that state. A list shows five rows and counts the rest. The panel's close button, Esc or a click on empty space
clears the focus. A second click or Enter on the focused body is held for drilling into it, which waits until a user
can be selected, so it changes nothing yet (`src/features/orbit/orbitFocus.ts`).

The view always shows one of these states:

| State | When | What it draws |
|---|---|---|
| Orbit | `/api/level` answers 200 | The orbit, and under its title a *Source drift* badge when a source reports states the config lacks or omits (the optional `drift: {added, removed}` of a source) |
| Loading | the first answer is pending | A note |
| No level | the server answers 404 or 501 | A note: this server has no level |
| Sign-in | 401, or 403 from the OIDC gate | A card linking `/auth/login` (*Your session ended*, or *This account can't read the level* with *Sign in as someone else*) |
| Error | any other failure, such as a window past the history | The message and **Retry** |

The page asks again every minute. A self-contained demo page (`starpulse demo`) answers `/api/level` itself, with
synthetic sources, and its address picks the state: `?view=graph`, `&suns=working`, `&gate=expired` or
`&gate=refused`, `&pace=fast|live`, `&measure=count`. Motion off in the page's preferences draws one still frame.

The right rail keeps one order in every view: the recent moves at the top and the legend at the bottom, each line
wrapped whole rather than cut to an ellipsis. Nothing on the page scrolls sideways, and every box that scrolls does so vertically with the Kanban columns' thin scrollbar, from one
shared rule at the end of `starpulse/web/src/style.css` that `src/shared/scroll.test.ts` holds to.

### Forward an instance's events to a hub

An instance sends its machine and runs events to a hub over HTTPS, a batch at a time, in log order. Each side is
config; neither needs the hub extras on the instance.

On the hub, one `[[sources]]` table per instance names the variable that holds that instance's token. Setting the
variable is the grant and removing the table (then restarting `serve`) is the revocation:

```toml
[[sources]]
name = "ana"                 # the instance; the hub stores its events as `<name>/<event_id>`
token_env = "ANA_FORWARD_TOKEN"

aggregates_only = false      # true: refuse any batch that opts in to names
```

On the instance, `[forward]` names the hub and the variable holding the token the hub issued:

```toml
[forward]
url = "https://hub.example.com:8766"
token_env = "HUB_FORWARD_TOKEN"
batch = 50                   # events per request, 1 to 200
```

- **What leaves.** Only the machine and runs streams, cut to the fields their contracts name (`machine`, `event`,
  `task` or `run`, `time`, and a run's `workflow`, `run_id`, `status`, `step`, `depends`). A field a producer added
  stays home.
- **Names stay home by default.** `actor` and `assignee` leave only while the instance is opted in. Run
  `starpulse forward opt-in`, `opt-out` or `status` (`--config` as for `serve`); the flag is
  `starpulse-forward.json` beside the config. The forwarder reads it before every batch, so an opt-out applies at the
  next send with no restart and no call to the hub, even while the hub is unreachable. A batch that failed while
  opted in is rebuilt from the log, so it goes out without names after an opt-out. A hub with `aggregates_only`
  answers an opt-in 403, and the forwarder sends that batch, and the ones after it, without names until the instance
  opts out and in again.
- **The Admin view's Forwarding card** lists what the next batch carries, as the forwarder cuts it, with the hub, when it
  last took a batch, why it did not, and a switch for the opt-in. `GET /api/forwarding` answers that status (`{"configured":
  false}` with no `[forward]` block) and `PUT /api/forwarding` takes `{"opt_in": bool}`, the flag the CLI sets; both answer
  only a loopback or private-network browser, and the page's own origin on a write.
- **Exactly once.** The forwarder reads the instance's event log from a cursor stored in the instance's own database
  (`forward:<url>`), not from a Redis consumer group. The cursor moves only after the hub answers 200, so a batch
  that fails, or a process killed between the send and the answer, is sent again whole; the hub stores each
  `event_id` once and drops the repeat. A new `url` replays the retained log to the new hub.
- **`POST /api/forward`** takes `{"opt_in": bool, "events": [{"event_id", "stream", "fields"}]}` (at most 200 events
  and 1 MiB) as a bearer. A missing or wrong token answers 401, an opt-in to an `aggregates_only` hub 403, a body
  that is no batch 400, and none of them writes anything. An invalid event is counted `rejected` in the 200 so it
  cannot hold the cursor; a 503 means the hub's log refused an event and the batch repeats.
- `[forward]` is for an instance; `serve --hub` refuses it.

## Write a board adapter

A board adapter connects StarPulse to a tracker. It is a module with a `board(settings, base)` function that
returns a `starpulse.board.Board`: `settings` is the rest of the `[board]` table and `base` is the config file's
directory. The `Board` says:

- which lifecycle machines the page draws (`machines`),
- how the tracker's tasks reach the page (`start`, which feeds each task as it changes, and `keys`, the task
  keys it recognizes),
- and optionally a `writer(task, status, actor)` for moves made on the page or by an agent (each task's `moves` may
  list the `writers` the machine declares per event), an `assign` for assignee changes, a `read`, `edit` and `archive` for the full task record and guarded edits and
  archives (`edit` needs `read`; the snapshot's `capabilities` says which the board has), a `complete(task)` that
  moves a Done task out of the lanes (the native board's to `completed/`, where `read` and `edit` still find it), a `create(title, details)` that
  makes a task in the board's starting lane with the details the page filled (description, priority, labels,
  milestone, assignee, dependencies, acceptance criteria) and answers with its id (`POST /api/tasks`;
  `capabilities.create`), and optionally milestone records: `milestones()`, `read_milestone(id)`,
  `create_milestone(title, details)` (answering with the new id), `edit_milestone(id, changes)` and
  `archive_milestone(id)` (`GET /api/milestones`, `GET /api/milestones/<id>`, `POST /api/milestones`,
  `POST /api/milestones/edit` and `POST /api/milestones/archive`; the writes answer only the loopback and private
  network, and a board that sets none answers 404), and doc records the same way: `docs()` (without bodies),
  `read_doc(id)`, `create_doc(title, details)`, `edit_doc(id, changes)` and `archive_doc(id)` (`/api/docs`,
  `/api/docs/<id>`, `/api/docs/edit` and `/api/docs/archive`). `serve` records every machine event (task- and run-keyed) and each Board lane change it
  places into StarPulse's own store (`starpulse_machine_events`, `starpulse_lane_changes`), and the page reads that
  store: a `Board` has no history of its own. In the same transaction the store folds each of them into
  summaries a read of flow health or the level can use instead of every row: `starpulse_step_summaries` (steps and
  seconds in the from-state, per UTC day, machine, from-state and to-state), `starpulse_cases` (each task's or run's
  current state, when it entered it and its last event), `starpulse_lane_intervals` (each stay in a lane) and
  `starpulse_lanes` (per source and lane, the tasks in it now and when one first entered it). A store whose summaries
  are empty builds them from its rows when it opens (`HistoryStore.build_summaries`), and one that predates the lane
  counts counts them from its intervals; `rebuild_summaries` replaces them and `summary_differences` lists where they
  differ from the rows. A hub gets the tables from its migrations (revisions `0005` and `0007`). The summaries follow
  the order events were recorded, and cover only the machines the page draws when the store opens.
  `/api/analytics/health` and `/api/level` (with `/api/level/trajectories`) read these summaries and never scan the two
  raw tables: health reads the stays that ended in its window or are still going and takes the tasks in each lane from
  the lane counts; the Board's level reads the trajectories of the tasks that changed lane in its window or the trailing
  12 weeks (which set the aging threshold) and of the tasks still waiting or working, and takes where the history begins
  and which sources reported from the lane counts. Their cost follows that activity, not the history's length (see
  [Scaling notes](#flow-read-scaling)). A history that supplies only `lane_rows` and `level_runs`, as the Board adapter
  hook does, is read whole, and a level on a machine other than the Board reads that machine's events whole.

`starpulse.adapters.boards.native`, the default, keeps tasks as Markdown files under `.starpulse/board/` and writes moves,
assignee changes and new tasks to them in Python, reads a task's full record (priority, description, acceptance
criteria, plan, notes and definition of done) back for the task view, applies an edit to a task's file in one write,
and archives a task by moving its file to `archive/tasks/` after a reason is appended to its comments.
A task record also carries `start_criteria`: each criterion of the `start_criteria` YAML block under the
description's `## Start Criteria` heading (`id`, `kind`, `expr`, `cmp` and `want` for its threshold), with its
`status` (`met`, `unmet`, `error` or `not evaluated`), `observed` value, `error` and `checked` time. With `[board]
criteria` set to a command, the server runs it in the config's directory with `{id}` replaced by the task's id, and
reads a JSON array from its output, one object per criterion with `id`, `status` (`met`, `not-met` or `error`),
`observed`, `error` and `checked_at`; its exit status is ignored when it prints that array. A task's results are reused for 30
seconds. A command that fails to start, runs longer than 10 seconds, prints no array, or leaves a criterion out marks the
affected criteria `error` with why, and the record still builds. With no command each criterion is `not evaluated`.
Each open task in the snapshot carries `workable` and `workable_since` (epoch seconds, null when not workable). A task is
not workable while a dependency is not done (completed, or in the `done` lane) or while it is Waiting and its Start
Criteria are not all met; `not evaluated` and `error` count as unmet, and a Waiting task with neither criteria nor
dependencies is workable. It is workable since the latest of when it entered its lane, when each dependency was done and
when a pass first saw its criteria all met. The server evaluates the criteria of Waiting tasks whose dependencies are
done in the background every 30 seconds through the same cache, never per page, and keeps that first-met moment in
`starpulse_criteria_met` while the criteria stay met, so a restart does not reset it.
The native board also keeps milestones in Backlog.md's format, so a Backlog.md project's milestone files read
unchanged: `milestones/m-N - slug.md`, with the front matter `id` and `title` and, under `## Description`, the sections `## Outcome`, `## Spec`
and `## ADRs` (bullet lists) and `## Retro`. The slug is the title lowercased, whitespace to `-`, `<>:"/\|?*` removed
and cut to 50 characters. A new milestone takes the next number past every file in `milestones/` and
`archive/milestones/`; an edit rewrites only the sections it names (keeping unknown sections and the text before the
first heading byte for byte) and renames the file when the title changes, and an archive moves the file to
`archive/milestones/`.
It keeps docs in Backlog.md's format too: `docs/<folder>/doc-N - slug.md`, with the front matter `id`, `title`, `type`
(`specification`, `guide`, `readme` or `other`), `created_date` and `updated_date` and the doc's text after it. A
subfolder of `docs/` such as `specs/` is part of the doc's path and stays through every edit. The slug is the title
with `<>:"/\|?*` read as a space, `'(),` dropped and runs of space made `-`, its case kept. A new doc takes the next
number past every file in `docs/` and `archive/docs/`; an update rewrites only the front matter lines it changes (and
`updated_date`) and the body it is given, renames the file when the title changes, and writes nothing when it
changes nothing; an archive moves the file to `archive/docs/`.
The native board's task `edit` writes every field of Backlog.md's task file and only the one it is given: the front
matter's `title`, `type`, `status` (spelled as the board's lane), `priority`, `milestone`, assignee (`profile`),
`labels`, `dependencies`, `references`, `documentation` and `modifiedFiles` (an empty one of the last three leaves its
key out), and the body's description, plan, notes, final summary, acceptance criteria and definition of done (an item
with its `n` keeps it, one without takes the next). `appendNotes` adds a line to the end of the notes, a non-blank
`comment` adds a comment, and `read` returns the comments as `{created, text}`, which an edit cannot set. `complete(task)`
refuses a task that is not Done and moves one that is to `completed/`.
`starpulse.adapters.boards.upstream_backlog` is the reference adapter for a tracker with its own
writer: it polls a Backlog.md project's Markdown files, puts every task in the team named by its `config.yml`'s
`project_name` (a project that sets none is refused, so no task lands in a default team), takes
the machine from the project's own statuses (any lane reaches any other, unless `machine` names a machine file
whose states are those lanes and whose `writers` reserve a move to an actor, such as `operator`), and writes moves
with the `backlog` CLI, answering a failed write with the CLI's output. An adapter with a writer subclasses
`BoardAdapterKit` with `writer` set, and the kit then checks that a move the operator may make is written and one
the machine leaves to the operator is refused to the agent. A board kit also declares `teams`, the team key the
adapter derives for each task it produces, and asserts each record carries it. `starpulse.adapters.boards.jira` reads a Jira project and has no writer. It imports the named workflow from the site's
`workflows/search` as the Board machine (a state per status, an event per transition, a global transition leaving every
other status), refusing a workflow with a status in no transition, two statuses that make one lane, or no single initial
transition. Each issue is a task in the lane of its status and the team of its Jira project; an issue it `Blocks` waits on
the blocker, and a status in Jira's done category settles it as `completed`. Name your module in `[board] type` and StarPulse imports it.

**Migrating from `Board.history`.** `Board.history` is removed: StarPulse's store is the only history, so a `Board`
that passes `history=` fails with `TypeError: Board.__init__() got an unexpected keyword argument 'history'`. Delete
the argument, and have the adapter report what happens to a task through `start` (the feed records each lane change it
places) or the event log; the page, `/api/history`, `/api/analytics/health` and `/api/level` read the store. To keep an
existing history, copy its lane changes and machine events into the store's `starpulse_lane_changes` and
`starpulse_machine_events` tables once; `HistoryStore.rebuild_summaries` then rebuilds the summaries over them.

## Public surface

What a release keeps compatible; a minor `0.y` release may break it, and its notes say so. Everything else in the package is
internal and can change in any release.

- The `starpulse` command line: its verbs, their JSON output and their exit codes.
- The documented entry point `python -m starpulse.claude_code`.
- The config file's keys and the machine YAML with its JSON Schema (`machine.schema.json`).

The modules an adapter may import, each exporting exactly the names in its `__all__`:

- `starpulse.board`: the board adapter seam (`Board`, `Written` and the writer, task, milestone and doc protocols).
- `starpulse.board_feed`: the feed a board adapter places tasks on (`BoardFeed`) and what following a stream needs of it.
- `starpulse.contracts`: the board, machine-event, runs (`Dag`, `RecentRun`) and insights (`Finding`) records, their JSON Schemas, and `RunsSink`.
- `starpulse.adapter_kit`: the test kit an adapter or insights engine author runs against their work, and the helpers that serve it.
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
`uv run pytest -n 4 --dist loadgroup` spreads it over four pytest-xdist workers; `loadgroup` keeps the tests that
share checkout state on one worker. CI sizes `-n` to its runner's memory with `ci/xdist_workers.py`.
A pull request's CI runs only the test files its changes can reach, chosen by `ci/select_tests.py` from the import
graph; a dependency, `conftest.py`, fixture, machine, schema or skill change runs the whole suite, and so does every
push to `main`.
`uv run lint-imports` checks the package layers, top to bottom: `api` and `cli` (the server's routes, the hub and the
command line), `adapters`, `projections` (the feed, the machine and analytics reads), `store` (the tables and the
event log), `settings`, then `domain` and `contracts`. A layer imports its own or one below; none import upward, and
`api` and `cli` never import each other. The top level holds only the public modules listed above, each a facade over
its layer.
`pnpm --dir starpulse/web run check` typechecks, lints, tests and builds the page.
The page's `web/src` is organized by feature: `api/` (types, `apiFetch`, the event stream), `features/<name>/` (a view with its
pure model and colocated tests), `render/` (the canvas), `shared/` and `demo/`. ESLint's `no-restricted-imports` holds a feature
to `api/`, `render/`, `shared/` and its own folder, so a feature never reaches into another's.
Every `/api` body is a pydantic model in `starpulse/contracts/api.py`, and the server builds each response through it.
The page's types are generated from those models: after changing one, run `uv run python -m starpulse.contracts.api`
(writes `starpulse/api.schema.json`) and `pnpm --dir starpulse/web run gen:types` (writes `starpulse/web/src/api/types.gen.ts`),
and commit both. CI's `api-types` job regenerates them and fails on any difference.
[`bench/`](bench/README.md) holds the hub-ingest, instance event-log and flow-read benchmarks, and the page-latency harness that times every
request and page surface against the 50 ms budget.

[`design/`](design/index.html) is the design mockup, a static page over a saved snapshot (`data.js`) and, behind
`?view=kanban`, a saved Board (`board.js`) drawn by `kanban.js`; view it with
`uv run python -m http.server 8781 --directory design`, and `uv run python -m starpulse.cli.demo --mockup design --out
mockup.html` writes it as one scrubbed file. A pull request that changes the page (`starpulse/web/**`), the mockup or
the preview itself gets one UI-preview comment from
[`.github/workflows/ui-preview.yml`](.github/workflows/ui-preview.yml): screenshots of each changed surface's
scrubbed demo, built by [`ci/ui_preview.py`](ci/ui_preview.py) against the demo config
[`ci/preview.toml`](ci/preview.toml), with the demos published to `trantor-org/starpulse-demo` under `pr-<N>/`
while the pull request is open. That config draws a fictional workspace at a working team's scale: the Board adapter
[`ci/demo_workspace.py`](ci/demo_workspace.py) serves a nine-lane Board whose In Progress opens a delivery machine and
the lifecycle machines in [`ci/workspace/`](ci/workspace), beside five DAG domains, and `starpulse.cli.demo` fills it with
synthetic tasks, sessions, runs and pools. Each changed sub-mockup, a `design/<dir>/index.html` layered over a scrubbed page
capture, is published beside the demos as `mockup-<dir>.html` with its scripts inlined. The preview is review context and never gates the pull request. A push to `main`
that touches the same paths republishes both demos under `main/`, the live demo linked above.

### Flow read scaling

Flow health and the level read the summaries the history store keeps on write, so a read costs the activity of its
window, of the trailing 12 weeks (the level's aging threshold) and of the tasks still in flight, not the length of the
history. [`bench/flow_reads.py`](bench/flow_reads.py) records 10 thousand, 1 million and 10 million Board lane changes at
a fixed rate into a SQLite store and reads the default week of each: the CPU p95 of health, the level and its trajectories
at 1 million and at 10 million stayed within 1.6x of the p95 at 10 thousand in every run (one run: health 6.5, 6.3 and
8.0 ms; level 171, 142 and 180 ms; trajectories 164, 135 and 155 ms), and no read touches the two raw tables. The full table and how to
rerun it are in [`bench/README.md`](bench/README.md#flow-reads). What still grows with the history: opening a store
whose summaries are empty folds every row once (about 6 minutes for 10 million lane changes), and a history that
supplies only `lane_rows` and `level_runs`, or a level on a machine other than the Board, is read whole.

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
