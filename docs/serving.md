# Serve and configure

## Serve

Open <http://localhost:8766>. The first serve creates `.starpulse/board/` in the working directory (beside the config file when `--config`
names one): a `config.yml`
holding the project name (that directory's name, the team its tasks are in), the lanes (To Do, In Progress, Done) and an empty `tasks/` directory, one Markdown file per task. The
Kanban view starts with no tasks: **New task**, at the top right beside the task count, opens a form for its title, description, priority, impact, urgency, labels,
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

The page is a Starlette ASGI app (`PageApp`) served by Hypercorn on one socket, on its own thread. The plain port
answers HTTP/1.1, and HTTP/2 to a client that opens with the HTTP/2 preface (prior knowledge, `curl
--http2-prior-knowledge`); a TLS port negotiates `h2` or `http/1.1` through ALPN, and also serves HTTP/3 on a QUIC (UDP) socket bound to the same
address and port number (the `aioquic` package, Hypercorn's `h3` extra). Every response over TCP carries `alt-svc: h3=":<port>"; ma=3600`,
so a client moves to HTTP/3 on its next request; a cleartext port has no HTTP/3, since QUIC requires TLS.

TLS is on when `starpulse.toml` sets both `tls_cert` and `tls_key`, paths relative to the config file's directory. Setting one without the other, or naming a
file that is not there, stops `serve` at start with the reason. With neither, the port is cleartext and sends no `alt-svc`. A change to either key replaces the
Page API child on `starpulse reload`; a client's certificate trust is its own, so `curl --cacert <cert>` or a browser that trusts the certificate reaches the HTTPS and HTTP/3 port.

The handlers are blocking, so each request runs on a pooled worker thread (`REQUEST_THREADS`, 128, the listen backlog)
and a crowd of pages queues for a worker rather than starting a thread each. The pooled workers keep the default thread
stack size, where the previous server gave them 256 KiB: the free-threaded build's RSS check (`test_crowd_rss.py`) runs
only on 3.14t.

An event stream (`/api/events`, `/api/lanes`, `/api/held`) leaves that pool for as long as it stays open and is counted
against `STREAM_LIMIT` (256) instead, so a crowd of long-lived streams never takes the worker a short request needs. A
stream past the limit gets `503` with `Retry-After: 5` and the client reconnects.

A request answered without reading its body, such as a push refused for its size or sent to a route that does not exist,
has the rest of the body read and discarded as the response starts, so a stop is never held by a client still sending.
Every method reaches the sign-in gate first; one the server does not serve (`PATCH`, `OPTIONS`, `TRACE`) is then
answered `501`.

A stopping server first tells the feed it is restarting, ends every open stream, waits up to 8 s (`DRAIN_S`) for the
requests it took and closes.

### Worker processes

`serve` is a supervisor over the contexts that run as their own `starpulse worker <context>` process: `api` (the Page API), `pulls` (Delivery), `scheduler`, `runs`, `history`, `search` (with an `[search] embeddings_url`) and `board` (the Start Criteria dating). `serve` always starts `pulls` and `scheduler` as children; for each other one whose `api_worker`,
`runs_worker`, `search_worker` or `board_worker` setting is false, the default, it starts the worker as a child, restarts it with a growing delay (1 s, doubling to 60 s; a child that
ran a minute restarts at once) when it exits, and stops it when `serve` stops on `SIGTERM` or Ctrl-C. The children read the same config and `database_url` and meet `serve` only in
the event log. A true setting means something outside `serve` runs that worker, so `serve` starts no child for it. No unit file is needed to run StarPulse.

The `api` child serves the page and the HTTP API. `serve` binds `--host` and `--port` once (or adopts the socket the service manager passes in), keeps that listening socket for the life of the process and starts `starpulse worker api` with it on the descriptor named by `STARPULSE_LISTEN_FD`. `serve` first builds the page's machines and board from the config and exits 1 with the reason when it cannot, so a bad `starpulse.toml` or `board.yaml` stops `serve` rather than a child that exits at every start; it also tells the child, in `STARPULSE_STATIC`, which page build it checked. The child reads the Board from the replica the `board` child publishes and starts no adapter watcher. A reload of the child starts the new one on the same socket, waits until it reports (`STARPULSE_READY_FD`) it is about to serve, or 30 s (`warm`) at most, then stops the old: the old one stops accepting, finishes its in-flight requests (up to 8 s) and exits, so a connection made meanwhile queues in the backlog and none is refused.

Every context is its own child, the light ones (`history`, `search`) included, so a restart, a reload and a memory limit each reach one context alone. Merging the light ones into one child would save their duplicated import floor; sharing that floor between separate children saves it without giving up the isolation.

On Linux `serve` starts one preloaded process before any thread, `python -m starpulse._internal.server.zygote`, that imports every supervised context's entry module (the Page API's excepted), freezes what it imported out of the garbage collector's way and waits on a socket from `serve`. Each child is a fork of it that runs the same `starpulse worker <context>` main, so the children share the pages of the interpreter and imports until they write to them, and a context still has its own process to restart, reload and limit. A child still dies with `serve`: it inherits the preloaded process's stdin pipe from `serve`. The Page API child is always a `subprocess` child, since it inherits `serve`'s listening socket. Where `fork` is not safe (macOS and Windows), or when the preloaded process fails to start or answer (`serve` logs one warning naming the preloaded process and starts every later child with `subprocess` instead), a child is a `subprocess` child with its own imports.

`starpulse reload` replaces the children whose installed code changed, tells those whose only change is their config block to re-read it, and re-executes `serve` when its own code changed, so a deploy restarts only what it changed. A reload that changes code any child runs also retires the preloaded process: it takes no more forks and exits when its last child has, and a new one that imports the installed code forks every replaced child, so a replaced child never runs the old preloaded code. See [Reloading a running serve](cli.md#reloading-a-running-serve).

`serve` also holds each child to a memory limit, sampled every 5 s. Past the soft limit it replaces the child: the new one starts, then the old one is stopped (killed after 10 s if it ignores `SIGTERM`). Past the hard limit it kills the child and starts a new one at once. Each action is logged as a warning naming the context, pid, size and limit. The size is the proportional set size on Linux (`Pss` in `/proc/<pid>/smaps_rollup`, which divides each page the forked children share among the processes that map it, so the shared floor is not charged to every child) and the resident size on macOS (`ps`), read with the standard library only; where there is no reader, as on Windows, `serve` logs one warning and runs the children without limits. A true `*_worker` setting means `serve` runs no child for that context, so no limit applies to it.

| Context | `soft_mb` | `hard_mb` |
| --- | --- | --- |
| `pulls` | 768 | 1536 |
| `scheduler` | 384 | 768 |
| `runs` | 512 | 1024 |
| `history` | 384 | 768 |
| `search` | 384 | 768 |

`[worker_memory.<context>]` overrides either key for a context (whole megabytes, 1 or more; `soft_mb` below `hard_mb`). An unknown context, an unknown key or a soft limit not below the hard one is refused at load by name.

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
consumers such as the scheduler act twice. `FEED_EVENT_RESEND` in the feed module is the table: `snapshot` is resent,
and `task`, `move`, `pulls`, `claim`, `dags`, `ledgers` and `scheduler` are not.
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

## Event store

`starpulse/_internal/store` keeps one append-only stream per subject, `(subject_kind, subject_id)`, in
`starpulse_stream_events` (migration 0027). A row is a typed envelope (`event_id`, `version`, `type`, `schema_version`,
`at`, `actor`, `writer`, `definition_hash`, `causation_id`, `correlation_id`) and a JSON `payload`.

- `EventStore.append(kind, id, expected_version, events)` is the one write path. It compares `expected_version` with the
  stream's head and raises `StaleVersion` on a mismatch; the unique `(kind, id, version)` constraint turns a racing
  writer's collision into the same error. The events and their outbox rows commit together or not at all.
- `starpulse_outbox` holds a row per event, `sent_at` null until `mark_sent` records its acknowledgement. A consumer
  reads `outbox_pending()` and gets each event at least once under its stable `event_id`.
- `Upcasters` upgrade an old `schema_version` while a stream is read; the stored row is never rewritten.
- Event-log pruning never touches these tables.
- `StoredEvent.position` is the event's global, increasing row id; `read_after(subject_kind, position, limit)` pages events
  past a position in that order.

## Machine registry

`MachineRegistry` (`starpulse/_internal/store/machine_registry.py`, migration 0030) keeps every machine definition ever
activated in `starpulse_machine_versions`, keyed by the hash of the whole compiled definition (writers and `migrations`
included), and one active hash per machine in `starpulse_machine_active`. Nothing prunes or rewrites either table.

- `MachineRegistry.append(...)` is `EventStore.append` for a command: it checks each State an Event names against the
  active `board` version and stamps the Event's `definition_hash`, so a replay reads each Event under the version that
  wrote it. It checks State existence only, not the legal From-To move.
- A change that drops or renames a State holding live Tasks is accepted only with a top-level `migrations` map in the
  machine file (`migrations: {doing: in_progress}`). `activate` then appends a `Remapped` Event to each affected Task and
  switches the active version in one transaction, each append checked against the Task's expected version: a Task that
  moved since it was read raises `StaleVersion` and rolls the whole change back.
- Without a mapping the change is refused, naming the States and Task ids. A mapping names one target per State, so a
  split of one State into two cannot be expressed and is refused until Tasks are moved by hand; a mapping to a State the
  new version lacks is refused too.
- Archived Tasks count as live. The live board is still file-based, so only the event-sourced Task streams are remapped.

`sync_definitions` (`starpulse/_internal/server/machine_sync.py`) activates the Board's `[board] machine` file against the
live Tasks and each file in `.starpulse/machines/` (the owners' definitions directory). `serve` runs it at start, once the
port is bound, in a child process (`python -m starpulse._internal.server.machine_sync`, exit 3 on a refusal) so the
server itself never loads the database stack; a refusal exits `serve` 1. It runs again before every reload (`starpulse reload`, `POST /reload`): a refused reload changes
nothing and the running workers stay on the active version.

## Task read model

`starpulse/_internal/readmodel` folds the `task` streams into tables that answer reads by index, so no read loads every
Task. A `Projector(engine, store)` folds events past its checkpoint (`read-model:tasks`, in `Checkpoints`); each batch of 500
commits its rows and the checkpoint together. `rebuild()` empties the tables and replays from position 0; a replay and an
incremental fold give the same rows. Given a `SearchIndex` as `search`, the projector also writes each folded Task's search
row in that transaction, in lane `archived` when the row is archived; no non-test code constructs it yet, so `serve` does not.

- `starpulse_tasks` (migration 0029) has a typed column per StarPulse field, JSON `fields`, `meta` and `comments`, and
  `seq`, the position of the last event folded into the row. `starpulse_task_criteria` holds one row per Criterion.
- Partial indexes `WHERE archived = 0` (`ix_starpulse_tasks_live_{id,state,milestone,assignee}`) keep the live set small
  whatever the archive holds. `ix_starpulse_tasks_seq` serves the delta read.
- `ReadModel(engine, declared)` is the query surface: `task(id)`, `snapshot(state=None)`, `with_field(name, value)`,
  `ready(state, done)` (live Tasks in `state` whose every dependency is in `done`; a dependency with no row blocks) and
  `since(seq, limit)` (the delta: rows changed after a cursor, archived included). Each statement is a SQLAlchemy `Select`
  in `readmodel.queries`; its test asserts the plan uses an index and has no table scan.
  `archived(before, limit)` pages the archive newest first (partial index `ix_starpulse_tasks_archived_updated`, migration 0031) and
  `position()` is the highest `seq`, the cursor a cache keys on.
- Only `readmodel` reads `readmodel.tables` (the `readmodel-table-private` import contract).

`BoardFeed(read_model=ReadModel(engine))` serves the page from it: the reader switch, with no bridge between the two
paths. The feed holds no Task; `_hot()` is one `snapshot()` per `position()`, `task`, `held` and `is_done` are single-row
reads, `cold_page` pages `archived`, and the snapshot carries no archived Task (`cold_done` is empty). The Scheduler's
`open_tasks` and the write guards go through the same reads. `follow_read_model()` publishes the Tasks changed since it last
ran as page deltas, to run after each `Projector.catch_up`. Without a read model the in-memory path serves unchanged until the
cutover passes one in. In this mode entered and workable-since times are approximated, and the overlays for runs,
pulls and acceptance criteria are empty on the board card; `/api/task/<id>` returns the full record. The search index is its
own FTS table, queried by term and never by loading Tasks; `put` still feeds it, so the cutover feeds it from the read model.
`ci/test_read_model_latency.py` (nightly) serves 20,000 Tasks with 18,000 archived and holds every read surface to the page
budget and the board to its soft memory limit.

## Task History

The native board records every successful Task write in the Task's `task` stream (`board/task_history.py`), beside the
task file it still writes. One wrapper around the board's `writer`, `assign`, `edit`, `archive`, `restore`, `complete`,
`retire` and `create` covers every entry path: the `starpulse task` verbs, `/api/tasks`, `/api/edit`, the page, the
Scheduler and the Unblocker, which all call those verbs.

- The Events are the intent the file's before and after show: `TaskCreated`, `FieldsEdited` (own columns and `meta`),
  `Transitioned` (both states), `CriterionAdded`, `CriterionChecked`, `CommentAdded`, `Claimed`/`Released`, `Archived` and
  `Rehydrated`. A refused write appends nothing.
- A Task whose stream is empty is seeded first with a `TaskImported` of its record, so a replay equals the row for tasks
  written before History.
- An append that finds the head moved reads it again and retries once, then raises `StaleVersion`.
- A board whose log is not attached records nothing.

A deployment declares its own Task fields in `[board.fields]`:

```toml
[board.fields]
area = { type = "string", queried = true }  # type: string, integer, number or boolean; a queried field gets an indexed generated column
```

`declared_fields(board)` parses the table and refuses a name that is not lower snake case or a type outside the four.
`check_fields(declared, fields)` raises `UndeclaredField` or `MistypedField` (a boolean is not an integer). `ensure_columns`
adds `field_<name>`, a VIRTUAL generated column over `json_extract(fields, '$.<name>')`, and a partial index on it for each
queried field; it is idempotent, so it runs at every start.

## Portable database contract

Board and lifecycle state (task lanes, lane changes, machine events, runs) lives in StarPulse's database, SQLite at
`database_url` or beside the config, and nowhere else. A project that embeds StarPulse, such as an agent workspace,
reads and writes that state through the `starpulse` CLI, the HTTP API or a board adapter ([adapters](adapters.md)),
and keeps no copy of its own: code in the project that stores or derives board state is a gap in this contract, and
the missing capability is filed against StarPulse. Because the database is the whole state, moving to another host is
copying the SQLite file, with no project-side migration.

## Config file

`starpulse serve --config starpulse.toml` reads one TOML file; `starpulse.toml` in the working directory is read
when it exists.

The default SQLite store must be on a local disk because WAL mode does not work on network filesystems such as NFS
or SMB. When the project or config lives on network storage, set `database_url` to a SQLite file on a local disk instead.

On every SQLite connection the store sets `journal_size_limit` to 64 MiB, so a checkpoint that resets the WAL
truncates it to that bound instead of leaving the file at its high-water mark, and runs `PRAGMA optimize` so
the planner statistics stay fresh. The limit bounds the file after a checkpoint; it does not cap growth between them.

```toml
# The tracker's web address: a task links to `<tracker_url>/tasks/<id>`. Unset, it opens in the page's own Kanban.
tracker_url = "https://tracker.example.com"

# The SQLite file that holds the history; unset, `starpulse-history.sqlite` beside the config.
database_url = "sqlite:////var/lib/starpulse/history.sqlite"

# How long `serve` keeps the event log's rows: it prunes older ones at start and hourly, so the table, a SQLite file
# and every reader's replay at boot stay bounded. A reader that was down longer than this resumes at the oldest kept
# row and records the span it missed in `starpulse_gaps`. A whole number of days, 1 or more.
event_log_retention_days = 7   # the default

# Where `serve`'s History child writes each row it prunes, before it deletes the row (see Event log archive): a directory, relative to
# this file unless absolute.
event_log_archive_dir = "starpulse-archive"   # the default

# The seconds a `GET /api/pulls` read may take, from accept to the last byte written, before `serve` logs a `slow_read`
# line for it: `queue_s`, `compute_s` and `write_s`, the seconds it waited for a handler thread, computed its answer
# and wrote it, `in_flight`, the `/api/pulls` reads running when it began, and `busy` and `streams`, the request workers
# in use (the read itself included) and the streams open when it was accepted. No other route is timed. Above 0.
slow_read_seconds = 1   # the default

# The memory limits (proportional size on Linux, resident size on macOS) `serve` holds each worker child to, in megabytes (see Worker processes): past `soft_mb` it
# replaces the child, past `hard_mb` it kills and restarts it. Contexts: `pulls`, `scheduler`, `runs`. Either key may be left out.
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
# claim_ttl = 1800   # seconds a claim lives without an Event by its session or a machine event of its run (harness telemetry keyed by the session id); past it StarPulse appends `Released` (naming the last renewal) and the Task moves to Needs attention (the State waiting on a person), or to its Ready or initial State when the machine has none
