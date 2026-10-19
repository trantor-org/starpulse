# Serve and configure

## Serve

Open <http://localhost:8766>. The first serve creates `.starpulse/board/` in the working directory (beside the config file when `--config`
names one): a `config.yml`
holding the project name (that directory's name, the team its tasks are in), the lanes (To Do, In Progress, Done) and an empty `tasks/` directory, one Markdown file per task. The
Kanban view starts with no tasks: **New task**, at the top right beside the task count, opens a form for its title, description, priority, labels,
milestone, assignee, dependencies and acceptance criteria and adds it to the first column, and
the Admin view's **Tracker** card has **Connect a tracker**, which opens a modal with one collapsible row per tracker (the native board, Backlog.md, Jira), each expanding to
numbered setup steps whose commands copy with one click (see [Connect a tracker](#connect-a-tracker)). The `starpulse` verbs, `task create`
among them, are written for an agent to run ([the Agent CLI](cli.md)) and work the same typed by hand; the page and the verbs write the
same board. While a board that can create tasks (the native one) has none, the Star Map says so under the breadcrumb, naming `uvx starpulse task create "My first task"`
and **New task** as the two ways to add one. If the directory has a Backlog.md project (`backlog/config.yml`), serve prints one
line naming it and the `starpulse connect backlog` command that shows it instead; the page's
snapshot carries the same line as `hint`, and Connect a tracker shows it with the command as a copyable block. StarPulse keeps its event log and history in
`starpulse-history.sqlite` beside its config file, or in the working directory without one. The page has no sign-in and listens on this machine only (`127.0.0.1`): `--host 0.0.0.0` widens it to
every interface so another computer on your network can open it, which you do only on a network you trust. A write (move, edit,
start, run, history window) is refused unless it is a JSON request (`Content-Type: application/json`) that either names no
`Origin`, as a script or `curl` does, or names this server's own, so a web page on another site cannot write through your browser.

`starpulse serve --port 8800 --hours 24` changes the port and how far back a task's latest move counts toward
where it is drawn (6 hours by default). Serve binds its address once the config is accepted and before it creates the board, opens the history or starts a
worker: when another process holds the port, it exits 1 with one line naming `--host:--port` and saying to pass `--port`,
and prints no startup line.
The Admin page's Server card overrides that window for everyone
viewing, and the `history.hours` row of the history store's `starpulse_settings` table keeps the override across restarts.

### Serve on a socket the service manager passes in

Under systemd socket activation, `starpulse serve` adopts the listening socket the manager holds instead of binding
`--host` and `--port`, so connections made while the server restarts queue on that socket rather than being refused.
It follows the `sd_listen_fds` protocol and reads two environment variables:

- `LISTEN_PID`: the socket is for this process only when it equals the server's own pid. A value naming another
  process, or none, binds `--host` and `--port` as before.
- `LISTEN_FDS`: how many sockets follow, from file descriptor 3. `1` is adopted; more than one stops the server with an
  error, since it serves one address.

The adopted socket's backlog and options stay as the manager set them, `--host` and `--port` are ignored, and the
startup line and the board's instance name (`starpulse-<port>`) name the socket's port. A `.socket` unit's
`ListenStream=` sets that address; `Accept=no` (the default) hands the server the listening socket itself.

Each accepted request runs on a pooled worker thread (up to the listen backlog of 128) with a 256 KiB C stack
(`REQUEST_STACK` in the server). The stdlib default of 8 MiB, and a new thread per request, is not returned on the
free-threaded CPython build after the thread exits, so a crowd of pages would leave that RSS behind; 256 KiB still
encodes a 1 MB snapshot, and later requests reuse the same workers. A 50-viewer Locust crowd therefore occupies 50 of
those workers, not one abandoned heap per request.

An event stream (`/api/events`, `/api/lanes`, `/api/held`) leaves that pool for as long as it stays open and is counted
against `stream_limit` (256 on `StarPulseServer`) instead, so a crowd of long-lived streams never takes the worker a
short request needs. A stream past the limit gets `503` with `Retry-After: 5` and the client reconnects.

### Worker processes

`serve` is a supervisor over the contexts that run as their own `starpulse worker <context>` process: `api` (the Page API), `pulls` (Delivery), `autopilot`, `runs`, `forwarding`, `history`, `search` (with an `[search] embeddings_url`) and `board` (the Start Criteria dating and the lane reconcile). `serve` always starts `pulls` and `autopilot` as children; for each other one whose `api_worker`,
`runs_worker`, `forwarding_worker`, `search_worker` or `board_worker` setting is false, the default, it starts the worker as a child, restarts it with a growing delay (1 s, doubling to 60 s; a child that
ran a minute restarts at once) when it exits, and stops it when `serve` stops on `SIGTERM` or Ctrl-C. The children read the same config and `database_url` and meet `serve` only in
the event log. A true setting means something outside `serve` runs that worker, so `serve` starts no child for it. No unit file is needed to run StarPulse.

The `api` child serves the page and the HTTP API. `serve` binds `--host` and `--port` once (or adopts the socket the service manager passes in), keeps that listening socket for the life of the process and starts `starpulse worker api` with it on the descriptor named by `STARPULSE_LISTEN_FD`. `serve` first builds the page's machines and board from the config and exits 1 with the reason when it cannot, so a bad `starpulse.toml` or `board.yaml` stops `serve` rather than a child that exits at every start; it also tells the child, in `STARPULSE_STATIC`, which page build it checked. The child reads the Board from the replica the `board` child publishes and starts no adapter watcher. A reload or restart of the child starts the new one on the same socket, then stops the old: the old one stops accepting, finishes its in-flight requests (up to 8 s) and exits, so a connection made meanwhile queues in the backlog and none is refused. A `serve --hub` serves its page in-process and gets no `api` child.

Every context is its own child, the light ones (`forwarding`, `history`, `search`) included, so a restart, a reload and a memory limit each reach one context alone. Merging the light ones into one child would save their duplicated import floor; sharing that floor between separate children saves it without giving up the isolation.

On Linux `serve` starts one preloaded process before any thread, `python -m starpulse._internal.server.zygote`, that imports every supervised context's entry module (the Page API's excepted), freezes what it imported out of the garbage collector's way and waits on a socket from `serve`. Each child is a fork of it that runs the same `starpulse worker <context>` main, so the children share the pages of the interpreter and imports until they write to them, and a context still has its own process to restart, reload and limit. A child still dies with `serve`: it inherits the preloaded process's stdin pipe from `serve`. The Page API child is always a `subprocess` child, since it inherits `serve`'s listening socket. Where `fork` is not safe (macOS and Windows), or when the preloaded process fails to start or answer (`serve` logs one warning naming the preloaded process and starts every later child with `subprocess` instead), a child is a `subprocess` child with its own imports.

`starpulse reload` replaces the children whose installed code changed, tells those whose only change is their config block to re-read it, and re-executes `serve` when its own code changed, so a deploy restarts only what it changed. A reload that changes code any child runs also retires the preloaded process: it takes no more forks and exits when its last child has, and a new one that imports the installed code forks every replaced child, so a replaced child never runs the old preloaded code. See [Reloading a running serve](cli.md#reloading-a-running-serve).

`serve` also holds each child to a memory limit, sampled every 5 s. Past the soft limit it replaces the child: the new one starts, then the old one is stopped (killed after 10 s if it ignores `SIGTERM`). Past the hard limit it kills the child and starts a new one at once. Each action is logged as a warning naming the context, pid, size and limit. The size is the proportional set size on Linux (`Pss` in `/proc/<pid>/smaps_rollup`, which divides each page the forked children share among the processes that map it, so the shared floor is not charged to every child) and the resident size on macOS (`ps`), read with the standard library only; where there is no reader, as on Windows, `serve` logs one warning and runs the children without limits. A true `*_worker` setting means `serve` runs no child for that context, so no limit applies to it.

| Context | `soft_mb` | `hard_mb` |
| --- | --- | --- |
| `pulls` | 768 | 1536 |
| `autopilot` | 384 | 768 |
| `runs` | 512 | 1024 |
| `forwarding` | 256 | 512 |
| `history` | 384 | 768 |
| `search` | 384 | 768 |

`[worker_memory.<context>]` overrides either key for a context (whole megabytes, 1 or more; `soft_mb` below `hard_mb`). An unknown context, an unknown key or a soft limit not below the hard one is refused at load by name.

The `forwarding` worker (`starpulse worker forwarding`) sends the event log to the `[forward]` hub, and only exists for a config with that table. `serve` runs no forwarder thread: it builds a
forwarder only to answer `GET /api/forwarding` and `PUT /api/forwarding`, which writes the opt-in through the event log for the worker, so `serve` still needs the `token_env` variable set. The forward cursor
lives in the history database, so a restarted worker neither drops nor repeats a forwarded event. The worker's last send, problem and refusal reach `serve` through the event log; `refused` can lag an opt-in
change by up to one forward interval (5 s). The worker logs `Forwarder:` lines, which a supervised child writes to `serve`'s output.

### What the page shows when the server restarts

The page keeps its last Board on screen while the connection is down and says why in the navigator's header, where the dot
and the `live · <time> MST` line sit. The note replaces that line until the connection is live again; `<time>` is the
clock time of the last data the page drew.

| State | Dot | Note | When |
| --- | --- | --- | --- |
| Live | green | `live · HH:MM MST` | The stream is open. |
| Restarting | amber, pulsing | `restarting · HH:MM MST` | The server sent `restarting` before it exited. |
| Retrying | amber, pulsing | `retrying · HH:MM MST` | The stream dropped with no announcement. |
| Offline | red | `offline · HH:MM MST` | The stream has been down for 20 s, from the drop or the announcement. It keeps retrying. |
| New build | green | `updating when idle` | The server runs a page build other than the one loaded. |

The dot does not pulse under `prefers-reduced-motion`.

The page reconnects at once after a drop, then waits 250 ms, 500 ms, 1 s, 2 s and 3 s between tries and keeps trying at 3 s.
Each connect replaces the page's Board with a fresh snapshot.

While the Board is replaying after a start, `/api/events` resends only `snapshot`, once the replay has ended, because a
reconnecting page needs the Board the replay built. Every other kind is a delta of that Board; resending it would make
consumers such as the autopilot act twice. `FEED_EVENT_RESEND` in the feed module is the table: `snapshot` is resent,
and `task`, `move`, `insight`, `pulls`, `claim`, `dags`, `ledgers`, `level`, `forwarding` and `autopilot` are not.
`build` and `restarting` are process announcements on an open stream, not replayed deltas.

Two events on `/api/events` carry what the page needs:

- `build` ({id}): the page build the server is serving, the first 12 hex digits of the SHA-256 of `static/index.html`
  (whose asset names carry each bundle's hash, so a rebuilt page has a new id). It follows the `snapshot` on every connect.
  The first build a page's first connection names is the build it was loaded from; a later connection that names another
  makes the page show `updating when idle`, once that connection's snapshot no longer carries `reading`: a page reloaded
  onto a server still reading its board would draw the partial Board it holds.
- `restarting` ({at}): sent to every open stream when the server receives `SIGTERM`, before it exits, after it has
  waited up to one second in all for the open streams to write the frame. The server then saves the Board and stops.

A page that holds a new build reloads itself once nobody is using it: no task view, dialog or menu open, no field focused,
and no pointer, key or wheel input for 30 s. A tab in the background reloads at once. It reloads once per build: the page
records the build it reloaded for in `sessionStorage` (`starpulse.reloadedFor`), so a build that still differs after the
reload does not reload it again.

A demo page plays these states with `?link=`: `restart`, `update` (a restart that ships a new build) and `drop` play from
live; `restarting`, `retrying`, `offline` and `updating` hold one state.

## Portable database contract

Board and lifecycle state (task lanes, lane changes, machine events, runs) lives in StarPulse's database, SQLite by
default or Postgres by `database_url`, and nowhere else. A project that embeds StarPulse, such as an agent workspace,
reads and writes that state through the `starpulse` CLI, the HTTP API or a board adapter ([adapters](adapters.md)),
and keeps no copy of its own: code in the project that stores or derives board state is a gap in this contract, and
the missing capability is filed against StarPulse. Because the database is the whole state, moving to another host is
copying the SQLite file (or pointing `database_url` at the same Postgres), with no project-side migration.

## Config file

`starpulse serve --config starpulse.toml` reads one TOML file; `starpulse.toml` in the working directory is read
when it exists. Database credentials never go in it: they come from the driver's environment, such as `PGPASSWORD`.

The default SQLite store must be on a local disk because WAL mode does not work on network filesystems such as NFS
or SMB. When the project or config lives on network storage, set `database_url` to a Postgres database instead.

On every SQLite connection the store sets `journal_size_limit` to 64 MiB, so a checkpoint that resets the WAL
truncates it to that bound instead of leaving the file at its high-water mark, and runs `PRAGMA optimize` so
the planner statistics stay fresh. The limit bounds the file after a checkpoint; it does not cap growth between them.

```toml
# The tracker's web address: a task links to `<tracker_url>/tasks/<id>`. Unset, it opens in the page's own Kanban.
tracker_url = "https://tracker.example.com"

# History in Postgres instead of SQLite; install the extra with `uvx --from 'starpulse[postgres]' starpulse serve`.
database_url = "postgresql+psycopg://db.example.com/starpulse"

# How long `serve` keeps the event log's rows: it prunes older ones at start and hourly, so the table, a SQLite file
# and every reader's replay at boot stay bounded. A reader that was down longer than this resumes at the oldest kept
# row and records the span it missed in `starpulse_gaps`. A whole number of days, 1 or more.
event_log_retention_days = 7   # the default

# Where `serve`'s History child writes each row it prunes, before it deletes the row (see Event log archive): a directory, relative to
# this file unless absolute. A `serve --hub` prunes no rows and writes no archive.
event_log_archive_dir = "starpulse-archive"   # the default

# The seconds a `GET /api/pulls` read may take, from accept to the last byte written, before `serve` logs a `slow_read`
# line for it: `queue_s`, `compute_s` and `write_s`, the seconds it waited for a handler thread, computed its answer
# and wrote it, `in_flight`, the `/api/pulls` reads running when it began, and `busy` and `streams`, the request workers
# in use (the read itself included) and the streams open when it was accepted. No other route is timed. Above 0.
slow_read_seconds = 1   # the default

# The memory limits (proportional size on Linux, resident size on macOS) `serve` holds each worker child to, in megabytes (see Worker processes): past `soft_mb` it
# replaces the child, past `hard_mb` it kills and restarts it. Contexts: `pulls`, `autopilot`, `runs`. Either key may be left out.
# [worker_memory.pulls]
# soft_mb = 768    # the default
# hard_mb = 1536   # the default

# The board adapter: a module under `starpulse`, or the dotted path of one an installed package provides.
# The rest of the table is that adapter's settings.
# With no [board] table the view draws its own Markdown board, `type = "native"`:
[board]
type = "native"
# path = ".starpulse/board"  # the board's directory, relative to this file; created empty when absent
# machine = "board.yaml"     # a machine file for the Board: its transitions and `writers` decide which moves are offered, and to whom; every other file in `.starpulse/machines/` is drawn as a flow. Every lane must be one of its states; a state that is not a lane must be `initial` or `final`, is drawn, and is never offered as a move (a creation or archive state), else `serve` refuses to start
# criteria = "my-evaluator {id}"  # evaluates a task's Start Criteria; {id} is the task's id (see docs/adapters.md)
# holds = "my-holds {id}"    # prints a JSON array of reasons the task actor withholds the task's `deps_done` (see Task actor)
# validate = "my_checks:task_write"  # may refuse a task write before it lands (see docs/adapters.md)
# types = ["spike", "bug"]  # the names a task's `type` may take; a write setting any other is refused with this list in its reason, so with no list any non-empty type is accepted and a board names none of its own
# task_file_name = "title"   # the name a created task's file is written under: "title" is `task-1 - Draw-the-board.md`, "slug" is `task-1-draw-the-board.md`, lowercase, its slug capped at 19 characters

# Rules every task write must satisfy, whoever makes it: the agent CLI, the page or a workflow (see Board rules in
# docs/public-surface.md for every primitive). Each is judged on the task as it will be after the write, by the actor
# that makes it, and the first one broken refuses the write with its `reason` (and `skill`), the same text to the CLI
# and the page; nothing is written. A board with no rules accepts every write it accepted before.
#   on       = { to = "Done" }                 a write that enters Done (`from = [...]` narrows it to those states)
#            | { to = "Done", while = true }   ... and a write that leaves the task in Done
#            | { write = true }                every write, whatever the task's state
#   require  = one primitive: field, label, section, body, block, dependencies, checklist, or all_of, any_of, exactly_one,
#              none_of over a list of them
#   unless_actor = ["dagu/reconciler"]         actors the rule does not judge: operator, agent, <instance>/<workflow>
# [[board.rules]]
# on = { to = "Done" }
# require = { field = { field = "references", matches = "/pull/\\d+$", min = 1 } }
# reason = "Done needs a pull request in references"
# skill = "completing-tasks"
# unless_actor = ["dagu/reconciler"]

# Optional: move a task on the facts its lane waits on (see Task actor). The table takes no keys; its presence turns the
# actor on, and the board must edit tasks, else `serve` refuses to start. With it, the [release] polling pass does not run.
# [board.actor]

# To draw a Backlog.md project instead:
# [board]
# type = "upstream_backlog"
# path = "backlog"       # the project's backlog/ directory, relative to this file
# command = "backlog"    # the upstream Backlog.md CLI (`npm i -g backlog.md`) that writes a move (`backlog task edit <id> -s <status>`); a fork of it that lacks `backlog init` is not it
# machine = "board.yaml" # as above
# interval = 60          # seconds between the full rescans that back the file watch up (2 where inotify is missing)

# To draw only a project's machines, for a hub whose tasks arrive as lane entries and machine events instances forward:
# [board]
# type = "machines"      # takes no other setting: it draws every file in `.starpulse/machines/` beside this file, the Board machine (`board.yaml`) among them, and follows no task source, reads no board directory and offers no write

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

# With `gh` on the PATH, `serve` keeps a pull request store, current from the lifecycle events, that `/api/pulls`, the `ci`
# trail and `[release]` read. false never updates it: no event is applied, `POST /api/pulls/refresh` answers 404, tasks carry
# no PR state, and `/api/pulls` answers only from rows the database already holds. Set it on a second instance beside one
# that reads the same repositories, so one store is kept.
# pull_requests = true

# Whether something outside `serve` runs the Page API (the page and the HTTP API). False, the default: `serve` binds the
# listening socket, keeps it, and supervises `starpulse worker api` as a child that serves from it. True: you run
# `starpulse worker api --config <this file>` yourself, which binds `--host` and `--port` (or adopts the socket the service
# manager passes in), and `serve` binds and supervises nothing for it.
# api_worker = false

# Whether something outside `serve` runs the Runs context (the run adapters and the pushed-runs follower). False, the default: `serve` supervises it as a child process, `starpulse worker runs`. True: you run
# `starpulse worker runs --config <this file>` yourself and `serve` starts no child for it. Either way `serve` runs
# none of them: it draws the workflows, pools and startable workflows the worker keeps in the event log
# (`runs.projection`), and the page's Run now still starts a workflow through the adapter. Run-stream cursors stay in the
# event log, so a restarted worker neither drops nor repeats a run entry. With the flag set and no worker running, no
# run is followed.
# runs_worker = false

# Whether something outside `serve` runs the Forwarding context (the forwarder that sends the event log to the `[forward]`
# hub). False, the default: `serve` supervises it as a child process, `starpulse worker forwarding`, when `[forward]` is
# set. True: you run `starpulse worker forwarding --config <this file>` yourself and `serve` starts no child for it.
# Either way `serve` runs no forwarder thread and still answers `GET` and `PUT /api/forwarding` from the event log and
# the history database. The forward cursor stays in the history database, so a restarted worker neither drops nor repeats
# a forwarded event. With the flag set and no worker running, nothing is forwarded.
# forwarding_worker = false

# Whether something outside `serve` runs the History context's writers (the machine-history recorder and the hourly
# prune of the event log). False, the default: `serve` supervises them as one child process, `starpulse worker
# flow-metrics`. True: you run `starpulse worker flow-metrics --config <this file>` yourself and `serve` starts neither thread.
# They run together because both write the history database. The recorder's cursor is saved with the rows it covers, so
# a restarted worker neither drops nor repeats a history row. A hub (`serve --hub`) keeps both threads in-process and
# ignores this setting. With the flag set and no worker running, no machine event is recorded and the log is not pruned.
# flow_metrics_worker = false

# Whether something outside `serve` runs the Search context's embedding catch-up (the thread that fills vectors for the
# indexed task text). False, the default: with `[search] embeddings_url` set, `serve` supervises it as a child process,
# `starpulse worker search`. True: you run `starpulse worker search --config <this file>` yourself and `serve` starts
# no thread and no child. Vectors are stored per batch in one transaction, keyed by the text's digest, so a restarted
# worker neither drops nor repeats an embedding; `serve` rereads the vectors it ranks by every 30 s. A hub
# (`serve --hub`) keeps no search index and ignores this setting. With the flag set and no worker running, no vector is
# written and search ranks by the vectors already stored, else lexically.
# search_worker = false

# Whether something outside `serve` runs the Board context's writers (the thread that dates when each Waiting task's
# Start Criteria were met, and the one-pass reconcile of the lanes the history missed). False, the default: `serve`
# supervises them as a child process, `starpulse worker board`. True: you run `starpulse worker board --config <this
# file>` yourself and `serve` starts no thread and no child. The dates are saved in the history and read back at start,
# and a lane is recorded under an id naming the task, the lane and when it entered, so a restarted worker neither drops
# nor repeats a lane row nor re-dates a task; `serve` rereads the dates every 30 s. A hub (`serve --hub`) keeps both
# writers in-process and ignores this setting. With the flag set and no worker running, no Start Criteria are
# evaluated, so a Waiting task with them never becomes workable. The release of dependents belongs to the `pulls` worker.
# The Board worker is also the only process that runs the board adapter's watchers: it publishes each changed task to
# the `board:replica` stream of the event log and checkpoints the Board every minute, and `serve` and the other
# workers read that replica (restoring the checkpoint, then tailing the stream) instead of running the adapter, so a
# task it places reaches them within half a second. A worker a hub manages, which has no Board child, is started with
# `--local-board` (`starpulse worker pulls|runs|autopilot --local-board`) and runs the adapter in its own process. With
# no Board worker running, `serve` and those workers stay not ready, with no Board once nothing is checkpointed.
# board_worker = false

# Let a producer that just saw a pull request close have its record read now instead of at the next minute's refresh:
# `POST /api/pulls/refresh` with `{"repo": "<owner>/<name>", "number": 12}` and `Authorization: Bearer <token>`. The PR store's
# thread reads that pull request alone (one single-PR GraphQL read, no listing) and publishes it as a refresh does; one
# asked for during a refresh is read after the repository in hand, ahead of that refresh's projection. The
# minute's refresh stays the fallback. 202 queued; 401 for a missing or wrong token; 403 for a repository this instance does not
# track; 400 for any other body. The value is the name of an environment variable, never the token; unset, or with no `gh`
# on the PATH, the route answers 404, and a named variable that is empty stops `serve`.
# refresh_token_env = "STARPULSE_REFRESH_TOKEN"

# One instance of a runs adapter, a module under `starpulse` or the dotted path of one an installed package provides
# (it offers `start(url)` and `follow(url, runs, log)`, and optionally `rerun(url)` and `declared_params(url, workflow)`, the parameter names a workflow declares, which `doctor` reads); its workflows are drawn as `<name>/<workflow>`.
[[runs]]
name = "dagu"
type = "dagu"
url = "http://dagu.example.com:8080"
run_safe = ["nightly"]                   # the workflows the page's Run now may start
domains = { Data = ["nightly", "etl"] }  # how the page groups this instance's workflows
token_env = "DAGU_INGEST_TOKEN"          # deprecated, goes in 0.5: the push token for this instance, read as a `[[producers]]` entry
                                         # of the same name (so name them apart); declare `[[producers]]` instead (docs/sources.md)

# Optional: a producer that posts machine events as CloudEvents (see docs/sources.md, Post machine events as CloudEvents).
# `POST /api/machine-events` answers 404 until one is declared. A producer writes only the machines and actors listed here.
[[producers]]
name = "ci-bot"                          # the CloudEvents `source` its events carry; unique
token_env = "CI_BOT_TOKEN"               # the environment variable holding its bearer token; never the token; no two producers share one
machines = ["delivery"]                  # the drawn machines it may write; leave out with `actors` for a producer that only reports runs
actors = ["ci"]                          # the actors it may write as

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

# Optional: the autopilot's policy. Every key is optional; with no [autopilot] table the defaults below apply.
# [autopilot]
# lane = "to_do"          # the lane whose tasks are eligible; unset: the board's initial lane
# review_lane = "review"  # the lane whose tasks' points are the review load
# unsized_points = 3      # the points a task with no `size-N` label counts as, a whole number of 1 or more
# idle_minutes = 30       # minutes a started session may sit idle with its task still open before it is settled
# state_dir = "state"     # where the older switch and run-ledger files are imported from, relative to this file; unset: beside it
# [autopilot.tier_weights]  # what a point costs on each agent tier; a tier left out keeps its weight
# fast = 1
# standard = 2
# deep = 4
# [autopilot.limits]        # each dimension's limit; a dimension left out keeps its limit
# cpu = 80       # host CPU, percent
# memory = 80    # host memory, percent
# sessions = 2   # default harness sessions in flight (used when a harness has no session_limits row)
# review = 20    # points of tasks in the review lane
# [autopilot.session_limits]  # optional per-harness session caps; a harness left out uses limits.sessions
# claude = 3
# cursor = 2

# Optional: release Waiting tasks natively. With the table present, `serve` moves a Waiting task to Ready once every task
# it depends on is Done (see Release); with no [release] table it releases none. The board must edit tasks and draw
# `waiting` and `ready` lanes, else `serve` refuses to start.
# [release]
# settle = "pin-bump"  # optional: a dependency citing a pull request in a [[repos]] repository settles only once the parent pins its merge commit
# settle = "release"   # or: a dependency citing a pull request in `repo` settles only once the running build contains its merge commit
# repo = "owner/name"  # settle = "release" only: the repository the running build is released from

# Optional: what harness telemetry is read against for missed skill loads and trace clusters (see Find missed skill
# loads and recurring work in docs/sources.md). Every key is optional; with no table nothing is declared, and no
# path is an area.
# [analytics]
# roots = ["/srv/repo", "/srv/repo/.claude/worktrees/*"]  # absolute checkouts a path is cut to an area under; `*` is one component
# stop_activities = ["Bash", "exec_command"]               # activities that say how a session ran, never a cluster's descriptors
# lifecycle_skills = ["starting-tasks", "completing-tasks"] # skills every task loads, left out of a cluster's skills
# [[analytics.skill_loads]]                                # what should load a skill: any of these
# skill = "operating-nas"
# activities = ["ssh root@nas-host"]                       # globs over an activity's name
# [[analytics.skill_loads]]
# skill = "verifying-claims"
# title = "^(validate|verify|check)"                       # a regular expression over the task's title, case-insensitive
# label = "validation"                                     # a label the task carries
# injected_openings = ["<task-notification"]               # a prompt opening with one is labelled `injected`, any other `human`
# [analytics.labeller]                                     # names a human prompt's intent at ingest; with none, no prompt is labelled
# url = "http://127.0.0.1:8006/v1/systemone"               # a typed-decision endpoint, sent the prompt's text; only its label is kept
# model = "intent"                                         # the checkpoint it asks
# instructions = "Classify this message an operator sent an AI coding agent."
# timeout = 2.0                                            # seconds it may take; slower, unreachable or no answer leaves the label empty
# [analytics.labeller.criteria]                            # each label and its definition; an answer that is none of them is `unsure`
# correction = "The agent did something wrong or must stop or undo it."
# approval = "Proceed, yes, continue, or an answer to a question the agent asked."
# operator_tools = ["AskUserQuestion", "ExitPlanMode"]    # tools whose result is the operator's answer: the silence before one is their wait
# claims = ['backlog_task\.py\s+start\s+(TASK-\d+)']        # group 1 is the task a command or `Skill` args claims
# completion_skill = "completing-tasks"                    # with `completion_call`, marks a session's task complete
# completion_call = 'backlog_task\.py\s+deliver\b'          # a shell command run after that skill loaded
# [[analytics.skill_machines]]                             # what a run under a skill reaches, in order, to conform (see Diff a fast run against a slow one in docs/sources.md)
# skill = "developing-test-first"
# stages = [
#   { name = "RED", activities = ["pytest", "make test*"], ok = false },  # a failing call matching a glob of `activities`
#   { name = "GREEN", activities = ["pytest", "make test*"], ok = true },
# ]

# Optional: rank search by meaning as well as by words (see `search` in docs/cli.md). `embeddings_url` is an
# OpenAI-compatible embeddings endpoint, local or cloud; with it unset, search is lexical and nothing calls out.
# [search]
# embeddings_url = "http://localhost:8080/v1/embeddings"  # optional: POSTed `{model, input}`, answered with `data[].embedding`
# model = "nomic-embed-text"                             # required with embeddings_url: the model the endpoint is asked for
# token_env = "EMBEDDINGS_TOKEN"                         # optional: the environment variable holding the endpoint's bearer token

# Optional: hold Cursor task sessions to a context limit (see `python -m starpulse.cursor_context` in docs/sources.md).
# [cursor_context]
# limit_tokens = 150000    # a session past this many context tokens is asked to checkpoint, then restarted fresh
# window_tokens = 200000   # the context window the pane footer's percent is read against; limit_tokens may not exceed it
# wrapup_s = 600           # seconds an asked session has to checkpoint before it is restarted regardless
```

## Autopilot

The autopilot is a switch, a capacity reading, an admission rule and a loop that acts on the rule. The switch is persisted in
the `autopilot.enabled` row of the history store's `starpulse_settings` table, so it survives a restart, and it starts off. A missing row,
an unreadable store or a malformed value reads as off. `[autopilot] state_dir` (relative to the config file; `serve` creates it) is where the older
state files are looked for. An older `starpulse-autopilot.json` beside the config or in `state_dir` is imported once on first read, keeping its modification
time as the row's `updated_at`, then renamed to `starpulse-autopilot.json.imported`.

`GET /api/autopilot` answers any address:

```json
{
  "enabled": false,
  "harness": "claude",
  "quietHours": {"start": "22:00", "end": "07:00", "timezone": "America/Phoenix"},
  "sampledAt": 1788307200.5,
  "dimensions": [{"name": "cpu", "use": 35.0, "limit": 80.0}],
  "inFlight": [{"task": "TASK-1", "title": "First", "model": "@agent-standard-high", "started": 1788307000.0, "url": "https://claude.ai/code/session_01"}],
  "next": {"task": "TASK-2", "title": "Second", "verdict": "waits", "reason": "cpu"},
  "pauses": [{"harness": "claude", "until": 1788344400.0, "reason": "usage limit"}],
  "sessionsByHarness": {"claude": {"use": 1.0, "limit": 3.0}, "cursor": {"use": 0.0, "limit": 2.0}}
}
```

`harness` is the harness the loop starts sessions on (default `claude`); `PUT /api/autopilot` with `{"harness": "<name>"}` selects another.
`quietHours` is the daily window in which the loop admits nothing, or `null` for none (see Quiet hours below).
`dimensions` lists `cpu`, `memory`, `sessions` and `review` in that order, each as its use against its limit; the
`sessions` meter follows the selected harness's cap from `[autopilot.session_limits]` (else `limits.sessions`).
`sessionsByHarness` names every harness's in-flight count against its own cap. A credit or usage pause for one
harness lands in `pauses` and blocks admission for that harness only.
`sampledAt` is epoch seconds, and `dimensions` is empty with `sampledAt` null until the first sample.

- `cpu` and `memory` are the host's busy share and used share, in percent, read from `/proc`.
- `sessions` counts the tasks with an active harness session.
- `review` sums the `size-N` labels of the tasks in `review_lane`; a task without one counts `unsized_points`.

`inFlight`, `next` and `pauses` come from the dispatch loop, so a server that runs none leaves them out.

- `inFlight` lists the sessions the loop started whose tasks are still running, oldest first, each with its task, title,
  agent profile, start time in epoch seconds and session address (`url`); it is `[]` when none runs.
- `next` is what the next pass would do, whatever the switch says: the task `decide` ranks first among those that fit, with
  `verdict` `starting` and `reason` `goes next`; when none fits, the top-ranked task with `verdict` `waits` and the first
  dimension it overfits as `reason`. Inside the quiet hours the top-ranked task `waits` with `reason` `quiet hours`,
  whatever room the host has. While a harness usage pause holds, it `waits` with `reason` `<harness> usage limit`. It is
  `null` before the first sample or with no workable task in the eligible lane. Reading it logs no decision.
- `pauses` lists each harness whose admission is paused until `until` (epoch seconds) after a usage or credit-limit
  start, with `reason` `usage limit`. The key is absent when none are paused.

`PUT /api/autopilot` with `{"enabled": true}` or `{"enabled": false}` sets the switch, and with
`{"quietHours": {"start": "HH:MM", "end": "HH:MM", "timezone": "<IANA zone>"}}` or `{"quietHours": null}` sets or clears
the quiet hours; a body may carry both. It answers the same body as the `GET`, and a body with anything wrong is a 400
that changes nothing. It answers only loopback and private-network (RFC 1918) addresses, with 403 elsewhere, and like every write it needs
`Content-Type: application/json`. A `serve` that runs no autopilot, an adapter-kit server, answers 404.

The sampler reads every 60 seconds. The first sample is a baseline; after it, a dimension going from below its limit
to at or over it, or back, logs one `StarPulse autopilot: <dimension> is full|free (<use> of <limit>)` line.

StarPulse Admin's Autopilot card shows it: the switch with **On** or **Paused**, a meter per dimension (amber from
80% of its limit, red past it, dimmed while the switch is off), the next pick as text (its task, title and `starting`
in green or `waits: <reason>` in yellow, or **Nothing eligible**), the count of sessions in flight (the Sessions
dimension's use, or the length of `inFlight` without it), and the quiet hours row. A click on the switch sends the
`PUT` with no dialog, and a refusal shows its reason under the switch. The card reads `next` from the same body when it
carries it, and shows no pick without it. It reads once when Admin opens and follows the `/api/events` `autopilot`
event after. A server with no autopilot (404) shows the card with its reason and no controls. The Kanban draws no
autopilot control. The Orbit view and Admin Forwarding card follow the same pattern for `/api/events` `level` and
`forwarding` (one GET when shown, then stream events; no timed refresh).

### Quiet hours

The quiet hours are a daily window, from `start` up to but not including `end` on `timezone`'s wall clock, in which the
loop admits nothing; an `end` before the `start` runs past midnight. Sessions already running continue, and the loop
still finishes and settles them: only admission stops, as with the switch off. The window is the `autopilot.quiet_hours`
row of `starpulse_settings`, so it survives a restart; no row, or one that cannot be read, is no window. Setting it wakes
the loop, so a window that no longer covers now admits at once. There is no config key: the operator sets it from
StarPulse Admin, whose Autopilot card has a **Quiet hours** row (a switch, start and end times, and Save) that
sends the browser's own zone with the times.

### Admission

`autopilot.admission.decide` answers, for each workable task in the eligible lane, whether it fits and where it ranks. It is
a pure function of the open tasks, the sampler's readings, the `[autopilot]` policy, the trajectory chain, each task's
forecast P(goal), and the run ledger.

- **Demand.** A task draws `size points x its tier's weight` percent of CPU and of memory, one session, and its points of
  review. The tier is the middle word of its profile (`@agent-standard-high` is `standard`); a tier with no weight, or no
  profile, prices at the dearest weight. Once 3 runs of the same tier and size are in the ledger, their mean peak replaces
  that prior.
- **Fit.** A task is admitted only if its demand is at most the headroom (limit less use) on every dimension; otherwise
  the decision names the first dimension it overfits.
- **Order.** The admitted tasks go in the order of critical-path depth, the task itself plus the longest chain of open
  tasks waiting on it. In shadow, the default, a second order is only logged: `value / dominant share`, where value is depth
  times P(goal) and dominant share is the largest `demand / limit` over the dimensions. P(goal) is the task's forecast
  chance of the goal in the eligible lane (`trajectory_analytics(...)["forecast"]`), else the chain's `p_goal` for that
  lane, and 1 when the lane has no history. The loop reads those ranks whenever `[level]` is set, including on an IC
  server that is not serving `--hub`. An optional predictor, a
  function from a task's title and description to a score, replaces P(goal) in that shadow value and is logged; a
  predictor that raises leaves the score empty.
- **Log.** Each decision logs one line:
  `StarPulse autopilot: <task> admitted|refused (<dimension> full) p_goal=<p> predictor=<score> shadow_rank=<n> enforced_rank=<n>`.
  Ranks number the admitted tasks from 1; a refused task has none.

The run ledger is the history store's `starpulse_autopilot_runs` table (migration 0016), one row per finished run: its task, tier,
points, outcome, duration in seconds, the peak demand it drew on each dimension and the epoch second it was recorded. Event-log pruning never deletes
it, and the store's snapshot carries it. A `starpulse-autopilot-runs.jsonl` in `state_dir` when set, else beside the config, is imported
once into an empty table, each run stamped with the file's modification time, then renamed to `starpulse-autopilot-runs.jsonl.imported`. While
the store cannot be read the ledger measures nothing, so admission prices every task at its declared demand.

### Dispatch

While the switch is on, the loop calls `decide` and starts the admitted tasks. It runs on events, never on a dispatch timer:

- a task enters the eligible lane (or a task there becomes workable);
- a harness session stops, or a started task changes;
- the switch turns on;
- the sampler's reading of a dimension crosses its limit;
- the feed's `autopilot` status event of a new sample says the next pick would start: a task's demand can fit a
  dimension's headroom without the dimension ever having reached its limit, so a crossing alone would leave it waiting.
  The loop reads that event from the feed it already subscribes to (the stream `/api/events` serves), once per sample.

Each pass starts the first admitted task, then decides again over readings that carry that task's demand, so two tasks that
do not fit together are never both started in one pass. A run holds its capacity from its start until its task leaves
`in_progress`; until the harness reports the session active the loop adds that demand to the sampler's readings itself.
A start that fails (`StartFailedError`) is logged and skipped until the next pass, unless the refusal names a usage or
credit limit: admission for that harness then pauses until the reset clock the message names (or five hours when it
names none), `GET /api/autopilot` lists it under `pauses`, and the next pick `waits` with `reason` `<harness> usage
limit`. A start that succeeds comments
`Autopilot started <task>: <session address>` on the task; a board that refuses the comment leaves the session started.

A session starts through `session_start_url` when the config sets it; the loop's request is
`POST <url>/start/<task>?harness=<selected harness>&mode=interactive&by=autopilot`, so the service can brief an unattended session
unlike one an operator opened (an operator's start has no `by`, and the page's `POST /api/start` body names `harness` with
`mode` defaulting to `interactive`). With none, the built-in starter runs
`tmux new-session -d -s starpulse-<task> -c <config directory> claude --remote-control <task> "Start <task>"` and needs
`tmux` and `claude` on `PATH`, so a board with no `[autopilot]` table and no `session_start_url` starts a task out of the
box. The built-in starter starts only Claude: with another harness selected it refuses the start, naming
`session_start_url`, and ignores `mode`.

When a run's task leaves the eligible lane and `in_progress`, the loop writes its outcome (the lane it went to), duration and
peak to the ledger. When the harness session stops while the task is still in those lanes, the run is written as
`session-ended` and the task is held out of admission until a person or the sweep moves it; a later tool or start on the
same session revives that run instead of starting another. A started session that has been idle longer than
`idle_minutes` (the harness's last active event, or its start before any) with its task still open is settled once: the
task moves to `needs_attention` with a comment saying why, and is never started again. A board with no editor, or no `needs_attention` lane, refuses the move; the loop logs the
refusal and retries on the next sampler period. The sampler period (60 seconds) is the only timer; it finishes and settles
runs and never admits.

The runs in flight, each task's last start time and the last capacity sample live in `starpulse_settings`
(`autopilot.inflight`, `autopilot.starts`, `autopilot.sample`), so a restart restores them: `GET /api/autopilot` still
lists the sessions, the loop still settles and records them, and a task it already started is not started again. A restart
logs `StarPulse autopilot: restored N in-flight`. A start still inside 15 minutes (`START_COOLDOWN`) is not admitted
even when the in-flight row is missing, so a restart that lost that row does not send a second `started`.
Held `session-ended` tasks and harness pauses live in the history store, so a restart still keeps those tasks out of
admission and keeps that harness paused.

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
  a commit containing that merge commit (`pins.link`, the rule that sets a pull request's `applied_by`); or, for a pin
  pushed with no pull request, the default branch of such a repository pins a commit containing it (`Pins.head`, its
  head commit read again at most once a minute and never saved).

A pull request the store does not hold, or holds open, holds the dependent, the fail-closed direction. A closed, unmerged
one never reaches the pin and is ignored. The bump is looked for among the store's merged pull requests, so one no task
cites still settles the dependency, while one older than the store's records is not found and holds it. The pointer and
containment reads are the memoized `gh` calls the pull request projection makes; a path a merge does not pin (GitHub's
404) is a remembered answer too, so only a read `gh` could not make is asked again.

`settle = "release"` with `repo = "owner/name"` is the rule for a repository this process is itself released from, so a
merge is live once the running build holds it, not once a parent pins it (it needs no `[[repos]]`, and `repo` is refused
under any other rule). A dependency task that cites a pull request in `repo` settles only when:

- the pull request is merged and the PR store holds its merge commit;
- the running build's commit contains that merge commit (`Pins.reaches`, the GitHub `compare` the pin rule uses).

The running build's commit is the `+g<sha>` of the PEP 440 local version of the installed `starpulse` distribution (a wheel
tagged `<tag>.post<n>+g<sha>`), read once per process. A build with no such commit (a release tag, a source checkout)
holds every such dependent, the fail-closed direction, as do a pull request the store does not hold or holds open; a
closed, unmerged one is ignored. A dependency citing a pull request in any other repository settles on Done. The rule is
re-derived each poll, so a restart onto the new build settles the dependents its merge is now live in.

## Task actor

With a `[board.actor]` table, `serve` runs the task actor: an in-process worker that moves a task out of a lane when a
fact that lane's machine state waits on (`waits`, [Public surface](public-surface.md)) holds, through the board's task
editor as actor `starpulse/task-actor`. The board must edit tasks, else `serve` refuses to start. The table takes no keys.

The actor reads the `waits` of the Board machine and the transition each wait's event draws, so it moves only along a
move the machine declares. For a task in a state with `waits`, the first fact that holds fires its event:

- `pr_terminal`: every pull request the task cites is merged or closed in the PR store. A merged one is written with its
  merge commit as the proof in the edit's comment.
- `deps_done`: the task has dependencies, every one is Done, its description declares no Start Criteria, and, under
  `[release] settle = "pin-bump"`, every dependency's pin bump has merged (the rule in Release).
- `deps_unresolved`: a dependency is not Done.
- `criteria_met`: the task's Start Criteria were last evaluated all `met`.
- `criteria_unmet`: a Start Criterion was last evaluated `unmet` or `error`.

The actor evaluates a task's Start Criteria with the board's evaluator (`[board] criteria`) on a thread of its own, when
the task is in a lane that waits on a criteria fact and has no result or one older than the evaluator's cache (30 s), and
re-derives the task when the result changes. A board with no `criteria` command fires neither criteria fact. A criterion
the evaluator cannot evaluate is not retried before its result is stale.

The board adapter may withhold `deps_done` with reasons (`Board.holds`; the native board's `[board] holds` command, run
in the config's directory with `{id}` replaced, prints a JSON array of them, and output that is no such array holds the
task). The actor writes the reasons once as a comment on the task, and re-derives every held task when a task is created.

It keeps a `pull request -> tasks` and a `task -> dependents` index, built at start and kept current from lane writes. A
change to a pull request in the store, a lane write or a merged pin bump re-derives only the tasks it reaches. The
actor reads a store save as it happens, so a pull request's move does not wait for the pin walk of the projection that
saved it; the tasks held for a pin bump are re-derived after that projection. At start
it re-derives every open task once, so a pull request that merged while the server was down still moves its task. With
the actor on, the 30-second pass of Release does not start; the actor settles and releases on the same rules, so
`[release]` still names the settle rule.

A write the board refuses is logged and counted, and is not retried until the task's facts change. `GET /metrics` carries:

- `starpulse_task_actor_refusals_total`: refused writes.
- `starpulse_task_actor_latency_seconds`: a histogram of the seconds from the fact being observed to the write landing.
- `starpulse_task_actor_projection_seconds`: a histogram of the seconds each projection of the pull request store ran,
  the pin walk included.
- `starpulse_task_actor_handoff_seconds`: a histogram of the seconds from a store save to the actor reading it. The
  bounds run to 600 s, so a handoff or projection past the 10 s bound shows.
- `starpulse_task_actor_criteria_errors{task}`: the Start Criteria of a gated task that could not be evaluated; such a
  gate never passes.
- `starpulse_task_actor_pin_held`: a gauge of Waiting tasks whose dependencies are done but wait for a pin bump to
  merge (`PinGate.unapplied`); one that stays above 0 is a pin that never merges.

Each move the actor writes names `starpulse/task-actor` on its `board:lanes` entry. The Delivery worker logs the
actor's note before the write, and `serve` reads the notes logged since its last read before it places a move no note
names yet, so a move the file watch places before the note arrives still names the actor. `GET /metrics` carries
`starpulse_board_lane_unattributed_total`, a counter of the `board:lanes` entries any process appended since `serve`
started that name no actor. A move placed while `serve` replays the Board that no note names, one made while it was down, names `starpulse/replay`, and a lane the reconcile repairs names `starpulse/lane-reconcile`.


## Conformance violations

`serve` judges every move against the machine that draws it, as `starpulse conform` ([Replaying history against the
machines](cli.md#replaying-history-against-the-machines)) does on the stored history, and `GET /metrics` carries two
counters for each machine the feed draws:

- `starpulse_machine_conformance_events_total{machine}`: the moves judged.
- `starpulse_machine_conformance_violations_total{machine}`: the moves no transition declares.

The `board` machine is judged on `board:lanes`, every other machine on `machine:events`. `serve` counts every entry
the log still retains before the first scrape and follows new ones after, so a restart recounts the retained entries
rather than starting at 0, and an entry pruned from the log leaves the count. Every machine has both series from the
first scrape, at 0 until a move arrives. The first lane seen for a task is placed unjudged, because the log keeps no
earlier history; the stored-history replay judges it from the initial state. Guards are not judged. A hub (`--hub`)
judges nothing and exports neither.

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
- The snapshot holds no Ledger row. A page opening a Ledger reads `GET /api/ledger/<event>/events`: SSE whose first event,
  `page`, is `{rows, more}` (the newest 20 rows, and whether older ones remain) and whose later `rows` events are
  `{rows}`, the rows of that event that are new or differ, so a Ledger no page has open costs no frame. The page asks
  `GET /api/ledger/<event>?before=<at>&limit=20` for each older page as `{rows, more}`, `before` being the `at` of the last
  row held. Rows sharing the boundary second come together, so a page can run past `limit` and walking it neither repeats
  nor skips a row; none is older than 24 hours; an event no workflow is tied to is 404. `mergeStrip` (snapshot, and in the
  `ledgers` event, which carries nothing else; null with no workflow tied to `MERGED`) counts the whole day without the
  rows: `{since, bucket, buckets}`, 96 buckets of 900 seconds from `since`, each
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

## Cold done tasks

A task is hot for 24 h (`HOT_S`) after it enters `done`, then cold: the board feed holds only its `id`, `state` and
`entered` time, and `GET /api/snapshot` omits it. A hot task keeps its record in `flows`; a lane change out of `done`
(a reopen) reloads the cold task from its board file onto its new lane within that one change, and cooling itself
publishes nothing, so a page keeps a card until it reloads. The page's snapshot (`/api/snapshot`) is slim:

- `flows` carries open and hot done tasks, each without `description` and `criteria` (read them from
  `GET /api/task/<id>`), and its `moves` as `move_set`, a key into the snapshot's `move_sets`;
- `settled` keeps the tasks created or settled since the start of the day before local midnight, and `milestone_done` (`{milestone: count}`)
  counts every settled completed task by milestone;
- `/api/snapshot?view=full` is the whole document the CLI verbs read: full tasks, every `settled` entry and `cold_done`,
  the ids of the cold done tasks.

`GET /api/done[?before=<entered>][&limit=20]` returns `{tasks, more}`, the next page of cold done tasks, newest done
first, each `{id, title, state, model, labels, milestone, type, entered}` read from the board on request. `before` is
the `entered` of the last task held; `limit` is 1-100. A board that cannot read a task answers 404. A cold task has no
`moves`, so moving it is a 409; `task show` and the held stream read it whole through its record.

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
the In Progress one to N, enough to scroll, and `&board=no-archived`, `no-attention`, `unlisted` or `fourteen` to reshape the Board for a Star Map
review: a state taken out, a state no tier names, or fourteen states over thirty-three paths.

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
