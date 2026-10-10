# Serve and configure

## Serve

Open <http://localhost:8766>. The first serve creates `.starpulse/board/` in the working directory (beside the config file when `--config`
names one): a `config.yml`
holding the project name (that directory's name, the team its tasks are in), the lanes (To Do, In Progress, Done) and an empty `tasks/` directory, one Markdown file per task. The
Kanban view starts with no tasks: **New task**, at the top right beside the task count, opens a form for its title, description, priority, labels,
milestone, assignee, dependencies and acceptance criteria and adds it to the first column, and
the Admin view's **Tracker** card has **Connect a tracker**, which opens a modal with one collapsible row per tracker (the native board, Backlog.md, Jira), each expanding to
numbered setup steps whose commands copy with one click (see [Connect a tracker](#connect-a-tracker)). If the directory has a Backlog.md project (`backlog/config.yml`), serve prints one
line naming it and the `starpulse connect backlog` command that shows it instead; the page's
snapshot carries the same line as `hint`, and Connect a tracker shows it with the command as a copyable block. StarPulse keeps its event log and history in
`starpulse-history.sqlite` beside its config file, or in the working directory without one. The page has no sign-in and listens on this machine only (`127.0.0.1`): `--host 0.0.0.0` widens it to
every interface so another computer on your network can open it, which you do only on a network you trust. A write (move, edit,
start, run, history window) is refused unless it is a JSON request (`Content-Type: application/json`) that either names no
`Origin`, as a script or `curl` does, or names this server's own, so a web page on another site cannot write through your browser.

`starpulse serve --port 8800 --hours 24` changes the port and how far back a task's latest move counts toward
where it is drawn (6 hours by default). The Admin page's Server card overrides that window for everyone
viewing, and `starpulse-settings.json` beside the config keeps the override across restarts.

## Config file

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
# criteria = "my-evaluator {id}"  # evaluates a task's Start Criteria; {id} is the task's id (see docs/adapters.md)
# validate = "my_checks:task_write"  # may refuse a task write before it lands (see docs/adapters.md)
# task_file_name = "title"   # the name a created task's file is written under: "title" is `task-1 - Draw-the-board.md`, "slug" is `task-1-draw-the-board.md`, lowercase, its slug capped at 19 characters

# Rules every task write must satisfy, whoever makes it: the agent CLI, the page or a workflow (see Board rules in
# docs/public-surface.md for every primitive). Each is judged on the task as it will be after the write, by the actor
# that makes it, and the first one broken refuses the write with its `reason` (and `skill`), the same text to the CLI
# and the page; nothing is written. A board with no rules accepts every write it accepted before.
#   on       = { to = "Done" }                 a write that enters Done (`from = [...]` narrows it to those states)
#            | { to = "Done", while = true }   ... and a write that leaves the task in Done
#            | { write = true }                every write, whatever the task's state
#   require  = one primitive: field, label, section, dependencies, checklist, or all_of, any_of, exactly_one,
#              none_of over a list of them
#   unless_actor = ["dagu/reconciler"]         actors the rule does not judge: operator, agent, <instance>/<workflow>
# [[board.rules]]
# on = { to = "Done" }
# require = { field = { field = "references", matches = "/pull/\\d+$", min = 1 } }
# reason = "Done needs a pull request in references"
# skill = "completing-tasks"
# unless_actor = ["dagu/reconciler"]

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
                                         # an instance with `token_env` and neither `type` nor `url` is push-only (see docs/sources.md)

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

# Optional: start a run when a board event arrives (see Triggers). `on` names the event, `start` the workflow as
# `<instance>/<workflow>` of a [[runs]] instance whose adapter has `start`, `when` filters the event's fields.
[[triggers]]
on = "lane"                              # `lane`: a task entered a lane; `machine`: a lifecycle machine event
start = "dagu/reconcile"
when = { lane = { equals = "done" } }    # optional: each field must match by `equals`, `in` or `exists`

# Optional: the autopilot's policy. Every key is optional; with no [autopilot] table the defaults below apply.
# [autopilot]
# lane = "to_do"          # the lane whose tasks are eligible; unset: the board's initial lane
# review_lane = "review"  # the lane whose tasks' points are the review load
# unsized_points = 3      # the points a task with no `size-N` label counts as, a whole number of 1 or more
# idle_minutes = 30       # minutes a started session may sit idle with its task still open before it is settled
# [autopilot.tier_weights]  # what a point costs on each agent tier; a tier left out keeps its weight
# fast = 1
# standard = 2
# deep = 4
# [autopilot.limits]        # each dimension's limit; a dimension left out keeps its limit
# cpu = 80       # host CPU, percent
# memory = 80    # host memory, percent
# sessions = 2   # harness sessions in flight
# review = 20    # points of tasks in the review lane

# Optional: release Waiting tasks natively. With the table present, `serve` moves a Waiting task to Ready once every task
# it depends on is Done (see Release); with no [release] table it releases none. The board must edit tasks and draw
# `waiting` and `ready` lanes, else `serve` refuses to start.
# [release]
# settle = "pin-bump"  # optional: a dependency citing a pull request in a [[repos]] repository settles only when the parent's pin bump has merged

# Optional: what harness telemetry is read against for missed skill loads and trace clusters (see Find missed skill
# loads and recurring work in docs/sources.md). Every key is optional; with no table nothing is declared, and no
# path is an area.
# [analytics]
# roots = ["/srv/repo", "/srv/repo/.claude/worktrees/*"]  # absolute checkouts a path is cut to an area under; `*` is one component
# stop_activities = ["Bash", "exec_command"]               # activities that say how a session ran, never a cluster's descriptors
# lifecycle_skills = ["starting-tasks", "completing-tasks"] # skills every task loads, left out of a cluster's skills
# [[analytics.skill_loads]]                                # what should load a skill: any of these
# skill = "operating-unraid"
# activities = ["ssh root@unraid"]                         # globs over an activity's name
# [[analytics.skill_loads]]
# skill = "verifying-claims"
# title = "^(validate|verify|check)"                       # a regular expression over the task's title, case-insensitive
# label = "validation"                                     # a label the task carries
```

## Triggers

A `[[triggers]]` table declares a run to start when a board event arrives. `serve` reads the event log and, for each
entry a trigger matches, calls that instance's runs adapter `start(url)` with the workflow once; nothing else is
needed on the instance, and the workflow need not be in `run_safe`, because the declaration is the authority.

| Key | Meaning |
|---|---|
| `on` | The event: `lane` reads `board:lanes` (a task entered a lane; fields `task`, `lane`, `time`, `team`, and `milestone`, `labels`, `assignee` when the task has them), `machine` reads `machine:events` (fields `machine`, `event`, `task` or `run`, `actor`, `time`). Required. |
| `start` | `<instance>/<workflow>`: a `[[runs]]` instance with a `type`, and a workflow of it. Required. |
| `when` | Optional filter, the machine guard's field match: a table of field name to exactly one of `equals` (a string, number or boolean), `in` (a non-empty list of those) or `exists` (a boolean). Every listed field must match; a field the entry lacks matches only `exists = false`. No `when` matches every entry of the event. |

Several tables may name the same event; an entry that matches two starts both. `serve` refuses to start when a table
is malformed, names an instance that is not configured or is push-only, or names an instance whose adapter has no
`start`.

- **Where it starts reading.** A trigger first started takes its place at the head of the event log, so what the log
  retains from before is not replayed into runs. The reader keeps one cursor in the history store (`triggers`), so a
  restart resumes after the last entry it handled and starts nothing that it handled before. A lane entry reaches the
  log for a trigger as it does for a hub: on a store that holds no lane history, the first read of the board places
  every task and each placement is a lane entry.
- **Once per entry.** An entry id starts a trigger's workflow at most once in a run of `serve`: an entry read again
  after a failed cursor save, or appended again under the same event id, starts nothing more. Delivery is
  at-least-once across a crash: one that falls between a start and its cursor save repeats that one start.
- **A refused start is dropped.** An adapter that answers `StartFailedError` is logged as `triggers: <start> was not
  started for <event id>` and the entry is not retried, so an unreachable adapter does not hold later events. A start
  that succeeds is logged as `triggers: started <start> (run <id>) for <event id>`.

## Autopilot

The autopilot is a switch, a capacity reading, an admission rule and a loop that acts on the rule. The switch is persisted in
`starpulse-autopilot.json` beside the config file (in the working directory with none), so it survives a restart, and it starts off.

`GET /api/autopilot` answers any address:

```json
{"enabled": false, "sampledAt": 1788307200.5, "dimensions": [{"name": "cpu", "use": 35.0, "limit": 80.0}]}
```

`dimensions` lists `cpu`, `memory`, `sessions` and `review` in that order, each as its use against its limit.
`sampledAt` is epoch seconds, and `dimensions` is empty with `sampledAt` null until the first sample.

- `cpu` and `memory` are the host's busy share and used share, in percent, read from `/proc`.
- `sessions` counts the tasks with an active harness session.
- `review` sums the `size-N` labels of the tasks in `review_lane`; a task without one counts `unsized_points`.

`PUT /api/autopilot` with `{"enabled": true}` or `{"enabled": false}` sets the switch and answers the same body. It
answers only loopback and private-network (RFC 1918) addresses, with 403 elsewhere, and like every write it needs
`Content-Type: application/json`. A `serve` that runs no autopilot, an adapter-kit server, answers 404.

The sampler reads every 60 seconds. The first sample is a baseline; after it, a dimension going from below its limit
to at or over it, or back, logs one `StarPulse autopilot: <dimension> is full|free (<use> of <limit>)` line.

The Kanban view's filters row shows it as a strip directly left of the task count: the switch, a meter per dimension
(amber from 80% of its limit, red past it), a **Next** pick whose color says whether it starts or waits, and
**Paused · N running** with the meters dimmed while the switch is off. A click on the switch sends the `PUT` with no dialog, and a
refusal shows its reason under the strip. The Sessions meter opens the sessions in flight when the server lists them; the
strip reads `inFlight` and `next` from the same body when it carries them, and shows no pick and an empty list without them. The
strip re-reads every 5 seconds while the Kanban view shows. A server with no autopilot (404) shows **Autopilot unavailable**.

### Admission

`autopilot.admission.decide` answers, for each workable task in the eligible lane, whether it fits and where it ranks. It is
a pure function of the open tasks, the sampler's readings, the `[autopilot]` policy, the trajectory chain and the run ledger.

- **Demand.** A task draws `size points x its tier's weight` percent of CPU and of memory, one session, and its points of
  review. The tier is the middle word of its profile (`@agent-standard-high` is `standard`); a tier with no weight, or no
  profile, prices at the dearest weight. Once 3 runs of the same tier and size are in the ledger, their mean peak replaces
  that prior.
- **Fit.** A task is admitted only if its demand is at most the headroom (limit less use) on every dimension; otherwise
  the decision names the first dimension it overfits.
- **Order.** The admitted tasks go in the order of critical-path depth, the task itself plus the longest chain of open
  tasks waiting on it. In shadow, the default, a second order is only logged: `value / dominant share`, where value is depth
  times P(goal) and dominant share is the largest `demand / limit` over the dimensions. P(goal) is the chain's
  `p_goal` for the lane (`trajectory_analytics(...)["chain"]`), and 1 when the lane has no history. An optional predictor, a
  function from a task's title and description to a score, replaces P(goal) in that shadow value and is logged; a
  predictor that raises leaves the score empty.
- **Log.** Each decision logs one line:
  `StarPulse autopilot: <task> admitted|refused (<dimension> full) p_goal=<p> predictor=<score> shadow_rank=<n> enforced_rank=<n>`.
  Ranks number the admitted tasks from 1; a refused task has none.

The run ledger, `starpulse-autopilot-runs.jsonl` beside the switch, holds one JSON line per finished run: its task, tier,
points, outcome, duration in seconds and the peak demand it drew on each dimension.

### Dispatch

While the switch is on, the loop calls `decide` and starts the admitted tasks. It runs on events, never on a dispatch timer:

- a task enters the eligible lane (or a task there becomes workable);
- a harness session stops, or a started task changes;
- the switch turns on;
- the sampler's reading of a dimension crosses its limit.

Each pass starts the first admitted task, then decides again over readings that carry that task's demand, so two tasks that
do not fit together are never both started in one pass. A run holds its capacity from its start until its task leaves
`in_progress`; until the harness reports the session active the loop adds that demand to the sampler's readings itself.
A start that fails (`StartFailedError`) is logged and skipped until the next pass. A start that succeeds comments
`Autopilot started <task>: <session address>` on the task; a board that refuses the comment leaves the session started.

A session starts through `session_start_url` when the config sets it. With none, the built-in starter runs
`tmux new-session -d -s starpulse-<task> -c <config directory> claude --remote-control <task> "Start <task>"` and needs
`tmux` and `claude` on `PATH`, so a board with no `[autopilot]` table and no `session_start_url` starts a task out of the
box. `POST /api/start/<task>` is unchanged and uses only `session_start_url`.

When a run's task leaves the eligible lane and `in_progress`, the loop writes its outcome (the lane it went to), duration and
peak to the ledger. A started session that has been idle longer than `idle_minutes` (the harness's last active event, or
its start before any) with its task still open is settled once: the task moves to `needs_attention` with a comment saying
why, and is never started again. A board with no editor, or no `needs_attention` lane, refuses the move; the loop logs the
refusal and retries on the next sampler period. The sampler period (60 seconds) is the only timer; it finishes and settles
runs and never admits.

The runs in flight are held in memory. A restart forgets them: a session started before it still counts toward capacity
once the harness sees it, but the loop neither settles nor records it.

## Release

With a `[release]` table, `serve` moves each Waiting task to Ready once all of its dependencies have settled, through the
board's task editor, which records a comment on the task. It checks every 30 seconds after the Board replay, so a task is
Ready within one poll of its last dependency settling. A board with no dependencies has nothing to release, and a config
without the table releases nothing.

A dependency settles when its task is Done: in the `done` lane, or completed. An archived dependency never settles, so its
dependents stay Waiting. A task whose description declares Start Criteria is left to them, whatever its dependencies.

`settle = "pin-bump"` is the stricter rule for a parent that applies a child repository by pin bump (`[[repos]]`; it is
refused without one). A dependency task that cites a pull request in such a repository settles only when:

- the pull request is merged and the PR store holds its merge commit;
- a later merged pull request of the same owner, in a repository that is not pinned, changed the submodule's path and pins
  a commit containing that merge commit (`pins.link`, the rule that sets a pull request's `applied_by`).

A pull request the store does not hold, or holds open, holds the dependent, the fail-closed direction. A closed, unmerged
one never reaches the pin and is ignored. The bump is looked for among the store's merged pull requests, so one no task
cites still settles the dependency, while one older than the store's records is not found and holds it. The pointer and
containment reads are the memoized `gh` calls the pull request projection makes.

## Event log archive

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

## The Ledger

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

## Machine rows

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

## Connect a tracker

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
