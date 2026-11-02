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
where it is drawn (6 hours by default). The config's top-level `host`, `port` and `hours` set the same three, so a unit
runs a bare `starpulse serve --config <path>`; a flag overrides its key, and with neither the defaults hold
(`127.0.0.1`, `8766`, 6 hours). Serve binds its address once the config is accepted and before it creates the board, opens the history or starts a
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
Without `aioquic` (the free-threaded build installs none) a TLS port serves `h2` and `http/1.1` only, with no QUIC socket and no `alt-svc`.

TLS is on when `starpulse.toml` sets both `tls_cert` and `tls_key`, paths relative to the config file's directory. Setting one without the other, or naming a
file that is not there, stops `serve` at start with the reason. With neither, the port is cleartext and sends no `alt-svc`. A change to either key replaces the
Page API child on `starpulse reload`; a client's certificate trust is its own, so `curl --cacert <cert>` or a browser that trusts the certificate reaches the HTTPS and HTTP/3 port.

The handlers are blocking, so each request runs on a pooled worker thread (`REQUEST_THREADS`, 128, the listen backlog)
and a crowd of pages queues for a worker rather than starting a thread each, until every worker is busy: the admission
middleware then answers any request, whatever its route, `503` with `Retry-After: 1` before a route sees it (the gRPC
ingest path, which has its own token, is outside it). The pooled workers keep the default thread
stack size, where the previous server gave them 256 KiB: the free-threaded build's RSS check (`test_crowd_rss.py`) runs
only on 3.14t. On that build mimalloc keeps freed pages resident until its purge delay lapses (3.6 GB resident
against about 1 GB live in one deployment, 1.5-1.7 GB with no delay), so `serve` sets `MIMALLOC_PURGE_DELAY=0` in every
child it supervises, the zygote included, unless its own environment already names a value, which the child keeps.

An event stream (`/api/events`, `/api/lanes`, `/api/held`) leaves that pool for as long as it stays open and is counted
against `STREAM_LIMIT` (256) instead, so a crowd of long-lived streams never takes the worker a short request needs. A
stream past the limit gets `503` with `Retry-After: 5` and the client reconnects. The same middleware owns the
stream's place: it is taken when the handler admits the stream and given back once, when the request ends, whether the
client left, the server stopped the stream or the handler refused it after admitting.

A request answered without reading its body, such as a push refused for its size or sent to a route that does not exist,
has the rest of the body read and discarded as the response starts, so a stop is never held by a client still sending.
Every method reaches the sign-in gate first, as a middleware ahead of the routes.

Each handler is a Starlette `Route` of its own, in match order: the streams, the reads, the writes (each with the
methods it answers), the page (`/`, `/board`, `/runs` and `/flow/<flow>` for a known flow) and last the build's files by
`StaticFiles`, which sets `ETag` and `Last-Modified` and answers a conditional request `304`. A file under `/assets/`
is kept for a year (`immutable`). A path under `/api/` is never a file (the `served` path convertor refuses it), so an
unknown one is `404`. A method a path does not take is Starlette's `405` with its `Allow`, `PATCH` and `OPTIONS`
included; a `HEAD` of a read or a stream is the headers of its `GET` with no body, and opens no stream. A
`POST` to a push this deployment leaves unconfigured is `404`.

`GZipMiddleware` (subclassed as `Gzip`) compresses a body over 64 KB at level 6 for a client that accepts gzip, on a
thread, and each event of a stream with a flush so a page decodes it as it arrives; `gzip;q=0` is a refusal. A
snapshot body (`Encoded`) carries its own gzip, level 1, made by the request that encodes it, and is sent as it is. A file
of 64 KB or less is sent uncompressed.

The snapshot is taken and encoded for each request that asks for it (`views.adapters.inbound.snapshots`); no process
holds a Task, an encoded snapshot or its gzip between requests. A stream that sends its snapshot by reference
(`ref /api/events/body/<key>`) holds that body for one fetch, released when the page reads it or the stream ends; a
second fetch is `404`. The column streams (`/api/held`, `/api/lanes`) share one take per feed revision on the
`ColumnViews` thread, so one change costs one live-set read however many streams it wakes.

A stopping server first tells the feed it is restarting, ends every open stream, waits up to 8 s (`DRAIN_S`) for the
requests it took and closes.

### Worker processes

`serve` is a supervisor over the contexts that run as their own `starpulse worker <context>` process: `api` (the Page API), `pulls` (Delivery), `scheduler`, `runs`, `flow-metrics`, `search` (with an `[search] embeddings_url`) `board` (the Start Criteria dating), and each run adapter a `[[runs]]` instance names (`dagu`, `github-actions`, `systemd`, one child per adapter). `serve` starts each as a child, restarts it with a growing delay (1 s, doubling to 60 s; a child that ran a minute restarts at once) when it exits, and stops it when `serve` stops on `SIGTERM` or Ctrl-C. The children read the same config and `database_url` and meet `serve` only in the event log. No unit file is needed to run StarPulse, and no setting turns a child off: `starpulse reload` picks the children whose code or config moved.

The `api` child serves the page and the HTTP API. `serve` binds `--host` and `--port` once (or adopts the socket the service manager passes in), keeps that listening socket for the life of the process and starts `starpulse worker api` with it on the descriptor named by `STARPULSE_LISTEN_FD`. `serve` first builds the page's machines and board from the config and exits 1 with the reason when it cannot, so a bad `starpulse.toml` or `board.yaml` stops `serve` rather than a child that exits at every start; it also tells the child, in `STARPULSE_STATIC`, which page build it checked. The child reads the Board from the read model the `board` child folds and starts no adapter watcher. A reload of the child starts the new one on the same socket, waits until it reports (`STARPULSE_READY_FD`) it is about to serve, or 30 s (`warm`) at most, then stops the old: the old one stops accepting, finishes its in-flight requests (up to 8 s) and exits, so a connection made meanwhile queues in the backlog and none is refused.

Every context is its own child, the light ones (`history`, `search`) included, so a restart, a reload and a memory limit each reach one context alone. Merging the light ones into one child would save their duplicated import floor; sharing that floor between separate children saves it without giving up the isolation.

On Linux `serve` starts one preloaded process before any thread, `python -m starpulse.runtime.zygote`, that imports every supervised context's entry module (the Page API's excepted), freezes what it imported out of the garbage collector's way and waits on a socket from `serve`. Each child is a fork of it that runs the same `starpulse worker <context>` main, so the children share the pages of the interpreter and imports until they write to them, and a context still has its own process to restart, reload and limit. A child still dies with `serve`: it inherits the preloaded process's stdin pipe from `serve`. The Page API child is always a `subprocess` child, since it inherits `serve`'s listening socket. Where `fork` is not safe (macOS and Windows), or when the preloaded process fails to start or answer (`serve` logs one warning naming the preloaded process and starts every later child with `subprocess` instead), a child is a `subprocess` child with its own imports.

`starpulse reload` replaces the children whose installed code changed, tells those whose only change is their config block to re-read it, and re-executes `serve` when its own code changed, so a deploy restarts only what it changed. A reload that changes code any child runs also retires the preloaded process: it takes no more forks and exits when its last child has, and a new one that imports the installed code forks every replaced child, so a replaced child never runs the old preloaded code. See [Reloading a running serve](cli.md#reloading-a-running-serve).

`serve` also holds each child to a memory limit, sampled every 5 s. Past the soft limit it replaces the child: the new one starts, then the old one is stopped (killed after 10 s if it ignores `SIGTERM`). Past the hard limit it kills the child and starts a new one at once. Each action is logged as a warning naming the context, pid, size and limit. The size is the proportional set size on Linux (`Pss` in `/proc/<pid>/smaps_rollup`, which divides each page the forked children share among the processes that map it, so the shared floor is not charged to every child) and the resident size on macOS (`ps`), read with the standard library only; where there is no reader, as on Windows, `serve` logs one warning and runs the children without limits.

| Context | `soft_mb` | `hard_mb` |
| --- | --- | --- |
| `pulls` | 768 | 1536 |
| `scheduler` | 512 | 1024 |
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

`starpulse/event_log/store` keeps one append-only stream per subject, `(subject_kind, subject_id)`, in
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

`MachineRegistry` (`starpulse/event_log/store/machine_registry.py`, migration 0030) keeps every machine definition ever
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

`sync_definitions` (`starpulse/runtime/machine_sync.py`) activates the Board's `[board] machine` file against the
live Tasks and each file in `.starpulse/machines/` (the owners' definitions directory). `serve` runs it at start, once the
port is bound, in a child process (`python -m starpulse.runtime.machine_sync`, exit 3 on a refusal) so the
server itself never loads the database stack; a refusal exits `serve` 1. A Board machine that strands live Tasks
(`StrandedTasks`, exit 4) is the exception at start: the other definition files are still synced, `serve` logs a
warning naming the States and Task ids, and it starts on the version that stays active. It runs again before every reload (`starpulse reload`, `POST /reload`): a refused reload changes
nothing and the running workers stay on the active version.

## Task read model

`starpulse/event_log/readmodel` folds the `task` streams into tables that answer reads by index, so no read loads every
Task. A `Projector(engine, store)` folds events past its checkpoint (`read-model:tasks`, in `Checkpoints`); each batch of 500
commits its rows and the checkpoint together. `rebuild()` empties the tables and replays from position 0; a replay and an
incremental fold give the same rows. Given a `SearchIndex` as `search`, the projector also writes each folded Task's search
row in that transaction, in lane `archived` when the row is archived and not Done (an archived Done Task keeps the `Done` lane); no non-test code constructs it yet, so `serve` does not.

- `starpulse_tasks` (migration 0029) has a typed column per StarPulse field, JSON `fields`, `meta` and `comments`, and
  `seq`, the position of the last event folded into the row. `starpulse_task_criteria` holds one row per Criterion.
- Partial indexes `WHERE archived = 0` (`ix_starpulse_tasks_live_{id,state,milestone,assignee}`) keep the live set small
  whatever the archive holds. `ix_starpulse_tasks_seq` serves the delta read.
- `ReadModel(engine, declared)` is the query surface: `task(id)`, `snapshot(done, since)` (the live set: unarchived Tasks
  outside the done lanes, or in one and changed at or after `since`, local midnight; partial index
  `ix_starpulse_tasks_live_set` on `(archived, state, updated_at)`, migration 0043), `held_states()`, `with_field(name, value)`,
  `ready(state, done)` (live Tasks in `state` whose every dependency is in `done`; a dependency with no row blocks) and
  `since(seq, limit)` (the delta: rows changed after a cursor, archived included). Each statement is a SQLAlchemy `Select`
  in `readmodel.queries`; its test asserts the plan uses an index and has no table scan.
  `archived(before, limit)` pages the archive newest first (partial index `ix_starpulse_tasks_archived_updated`, migration 0031) and
  `position()` is the highest `seq`, the cursor a cache keys on.
- Only `readmodel` reads `readmodel.tables` (the `readmodel-table-private` import contract).

`BoardFeed(read_model=ReadModel(engine))` serves the page from it: the reader switch, with no bridge between the two
paths. The feed holds no Task: each `snapshot()` queries the live set, so a Task Done before local midnight is off the
Board and read only by id; `task`, `held` and `is_done` are single-row reads, `is_resident` is always false,
`cold_page` pages `archived`, and the snapshot carries no archived Task (`cold_done` is empty). The Scheduler's
`open_tasks` and the write guards go through the same reads. `follow_read_model()` publishes the Tasks changed since it last
ran as page deltas, to run after each `Projector.catch_up`. Without a read model the in-memory path serves unchanged. `serve`
folds the History into the read tables every 0.5 s (`Projector.catch_up`, then `follow_read_model`), draws the board from them
so the board reader opens no task file. The read model is the only read path: the old `read_model` config key is retired and ignored. Run `starpulse import-board` first. In this mode entered and workable-since times are approximated, and the overlays for runs,
pulls and acceptance criteria are empty on the board card; `/api/task/<id>` returns the full record, whose `createdBy` is the session that filed the task (`created_by` in its front matter, empty when none). The search index is its
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
# Every top-level key and table is described in the settings reference below; a setting left out takes its default.
tracker_url = "https://tracker.example.com"
database_url = "sqlite:////var/lib/starpulse/history.sqlite"
event_log_retention_days = 7   # the default
event_log_archive_dir = "starpulse-archive"   # the default
slow_read_seconds = 1   # the default
# pull_requests = true
# refresh_token_env = "STARPULSE_REFRESH_TOKEN"
# take_over_command = ["/usr/local/bin/take-over"]

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
# unfinished = "my-unfinished {id}"  # prints a JSON array of the work a task whose pull requests merged still has; the task actor routes it to Ready instead of closing it (see Task actor)
# parked = "my-parked {id}"  # runs after the task actor moves a task from the working lane to Waiting, to tell the session that holds it (see Task actor)
# released = "my-released {id}"  # runs after the task actor moves a task from Waiting to Ready, so a session parked mid-work is resumed whether or not anything admits Ready tasks (see Task actor)
# delivered = "my-delivered {id} {verdict}"  # runs once when a delivery run ends (its DELIVER_FINISHED event), with the run's verdict such as `green` or `red test`, so the session holding the task resumes on it (see Task actor)
# returned = "my-returned {id}"  # runs after the task actor moves a task from Review back to the working lane (its pull request turned draft or conflicting), so the session that delivered it is woken to fix it
# closed = "my-closed {id}"  # runs after the task actor moves a task to Done, so the board can file what follows the close (see Task actor)
# validate = "my_checks:task_write"  # may refuse a task write before it lands (see docs/adapters.md)
# claim_ttl = 1800   # seconds a claim lives without an Event by its session or a machine event of its run (harness telemetry keyed by the session id); past it StarPulse appends `Released` (naming the last renewal) and the Task keeps its State with no Assignee, free for any session to claim, and the sweep gives it back to the released session, as a `Claimed`, when that session acts again (an Event or machine event after the release) while no session holds it; the sweep reads the board feed, and a release is refused when the task file has since left that State or another session holds it
# transcripts = "~/.claude/projects"  # where Claude Code writes each session's transcript; a claim whose session's last turn there is a terminal halt (a synthetic error reply opening `Autocompact is thrashing`), with no renewal after it, is released at once rather than at `claim_ttl`, its comment naming the halt; only the transcript's last 64 KiB is read, and a missing transcript keeps the TTL
# sessions = "~/.claude/sessions"  # where Claude Code registers each running session as `<pid>.json`; a claim whose session (or bridge) id is registered there with its process still running, the pid's start time matching, is kept past `claim_ttl` and expires `claim_ttl` after each pass that finds it so, since a session waiting on a background task emits nothing; a halt still releases it, and an unreadable or missing directory keeps the TTL
# workflows = "http://localhost:8233"  # a Temporal server (its UI port) whose running workflows keep a claim: a workflow waiting on CI emits no Event, so a task that `workflows_query` matches a running workflow for, by the task id its workflow id ends in (`task-lifecycle/TASK-9`), renews its claim on every sweep pass, and the TTL runs from the last pass that saw it running; a pass that cannot read the server judges no claim; unset reads none
# workflows_query = 'ExecutionStatus="Running"'  # the Temporal visibility query that lists those workflows, such as `WorkflowType="task_lifecycle" AND ExecutionStatus="Running"`
# types = ["spike", "bug"]  # the names a task's `type` may take; a write setting any other is refused with this list in its reason, so with no list any non-empty type is accepted and a board names none of its own
# task_file_name = "title"   # the name a created task's file is written under: "title" is `task-1 - Draw-the-board.md`, "slug" is `task-1-draw-the-board.md`, lowercase, its slug capped at 19 characters

# Task fields this deployment adds to StarPulse's own, checked on write and kept in the read model (see Task read model):
# [board.fields]
# area = { type = "string", queried = true }  # type: string, integer, number or boolean; queried gives an indexed generated column, so a read filters by this field without a scan

# Rules every task write must satisfy, whoever makes it: the agent CLI, the page or a workflow (see Board guards in
# docs/public-surface.md for every primitive). Each is judged on the task as it will be after the write, by the actor
# that makes it, and the first one broken refuses the write with its `reason` (and `skill`), the same text to the CLI
# and the page; nothing is written. A board with no rules accepts every write it accepted before.
#   on       = { to = "Done" }                 a write that enters Done (`from = [...]` narrows it to those states)
#            | { to = "Done", while = true }   ... and a write that leaves the task in Done
#            | { write = true }                every write, whatever the task's state
#   require  = one primitive: field, label, section, body, block, dependencies, checklist, readable, or all_of, any_of, exactly_one,
#              none_of over a list of them
#   unless_actor = ["dagu/reconciler"]         actors the rule does not judge: operator, agent, <instance>/<workflow>
# [[board.guards]]
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
# interval = 2           # seconds between the scans that find a changed task file

# To draw only a project's machines, with no task source:
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


# [ci]
# states = ["in_progress", "review"]

[[runs]]
name = "dagu"
type = "dagu"
url = "http://dagu.example.com:8080"
run_safe = ["nightly"]                   # the workflows the page's Run now may start
domains = { Data = ["nightly", "etl"] }  # how the page groups this instance's workflows; leave it out and `serve` reads each DAG's
                                         # `domain=<name>` label from Dagu as it starts instead (`-and-` reads as " & ", other `-` as a
                                         # space: `domain=Delivery-and-CI` is "Delivery & CI"); with Dagu unreachable its DAGs are drawn outside any domain until a restart

[runs.commit]
after = "AFTER"
before = "BEFORE"
force = "FORCE"
task = "TASK"

[[producers]]
name = "ci-bot"
token_env = "CI_BOT_TOKEN"
machines = ["delivery"]
actors = ["ci"]
# adapter = "dagu"  # optional: a run adapter type whose own status labels its Step events carry, read through its `status_of`

[[repos]]
name = "skills"
path = "skills"
applied_by = "pin-bump"

# [release]
# settle = "pin-bump"  # or "release", with `repo = "owner/name"`


# Optional: the scheduler's policy. Every key is optional; with no [scheduler] table the defaults below apply.
# [scheduler]
# lane = "to_do"          # the lane whose tasks are eligible; unset: the board's initial lane
# review_lane = "qa"     # the lane whose tasks' points are the review load; unset: the board's lane that waits on a pull request
# unsized_points = 3      # the points a task with no `size-N` label counts as, a whole number of 1 or more
# idle_minutes = 30       # minutes a started session may sit idle with its task still open before it is settled
# state_dir = "state"     # where `starpulse migrate` imports the older switch and run-ledger files from, relative to this file; unset: beside it
# [scheduler.tier_weights]  # what a point costs on each agent tier; a tier left out keeps its weight
# fast = 1
# standard = 2
# deep = 4
# [scheduler.priority_matrix]  # the Priority weight of an <impact>/<urgency> cell (low, medium or high each); a cell left out keeps its weight
# "high/high" = 9
# default = 4               # a task with no Impact or Urgency ranks with this weight
# [scheduler.limits]        # each dimension's limit; a dimension left out keeps its limit
# cpu = 80       # host CPU, percent
# memory = 80    # host memory, percent
# sessions = 2   # default harness sessions in flight (used when a harness has no session_limits row)
# review = 20    # points of tasks in the review lane
# [scheduler.session_limits]  # optional per-harness session caps; a harness left out uses limits.sessions
# claude = 3
# cursor = 2
# verify_lane = "verifying"       # optional verify lane: its tasks take a `Verify TASK-N` session once the eligible lane has none to admit; set with verify_profile
# verify_profile = "@agent-standard-medium"  # the agent profile every verify session starts on; the built-in starter passes it as `--agent`

# Optional: what harness telemetry is read against for missed skill loads and trace clusters (see Find missed skill
# loads and recurring work in docs/sources.md). Every key is optional; with no table nothing is declared, and no
# path is an area.
# [analytics]
# roots = ["/srv/repo", "/srv/repo/.claude/worktrees/*"]  # absolute checkouts a path is cut to an area under; `*` is one component
# stop_activities = ["Bash", "exec_command"]               # activities that say how a session ran, never a cluster's descriptors
# lifecycle_skills = ["starting-tasks", "completing-tasks"] # skills every task loads, left out of a cluster's skills
# size_bands = { 1 = [50, 14], 5 = [170, 47] }          # each size -> [p90 steps, p90 active minutes]; `analytics estimates` reads the effort size from them
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
# claims = ['\.venv/bin/backlog-task\s+start\s+(TASK-\d+)']        # group 1 is the task a command or `Skill` args claims
# completion_skill = "completing-tasks"                    # with `completion_call`, marks a session's task complete
# eval_attribute = "my.eval"                               # the OTLP attribute that stamps an eval run's purpose; none: no run is an eval
# ladder = ["haiku-low", "haiku-high", "sonnet-high"]      # `<family>-<effort>` profiles, cheapest first; a move up is a raise
# default_repo = "owner/name"                              # the repository `analytics scores` reads without --repo
# completion_call = '\.venv/bin/deliver\b'                 # a shell command run after that skill loaded
# [analytics.weights]                                      # task score part weights over the built-in ones
# clean = 40
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

# Optional: map the steps a shipped skill names to this project's own command lines (see `command run` in docs/cli.md).
# Each name maps to an argv, run with no shell. Placeholders: {task}, {worktree}, {NAME} (from --arg NAME=VALUE), and the
# whole element {args} (the arguments after `--`); write a literal brace as `{{` or `}}`. `starpulse config check` refuses a malformed entry.
# [project.commands]
# deliver = ["./bin/ship", "{task}"]
# test = ["make", "test", "{args}"]

# Optional: hold Cursor task sessions to a context limit (see `python -m starpulse.runtime.cursor_context` in docs/sources.md).
# [cursor_context]
# limit_tokens = 150000    # a session past this many context tokens is asked to checkpoint, then restarted fresh
# window_tokens = 200000   # the context window the pane footer's percent is read against; limit_tokens may not exceed it
# wrapup_s = 600           # seconds an asked session has to checkpoint before it is restarted regardless
```

### Runs adapters

A `[[runs]]` instance's `type` names one of the built-in adapters `dagu`, `github_actions`, `systemd` and `temporal`, or an installed
package's module. `serve` starts the worker of each built-in adapter that a configured instance names, as its own child
(`starpulse worker dagu --config <this file>`, likewise `github-actions`, `systemd` and `temporal`), and restarts it if it stops, as
it does its other workers. No OS service unit is needed for an adapter. With its worker down or not yet started, the
page shows the instance with the error "the dagu worker has not reported" or "last reported Ns ago" (its beat is older
than 60s).

The Dagu Adapter reads a DAG's declared rerun safety from its Dagu labels (a value allows only `a-z A-Z 0-9 - _ . /`):
`rerun=safe` (a rerun repeats nothing), `rerun-key=<key>` (effects keyed by `<key>`, so a rerun for the same key repeats
none) or `rerun-repeats=<why>` with `rerun-step=<step>` (the step that repeats); a DAG with none serves `rerun: null`. It
also serves the share of all the host's cores the `dagu*.service` units used since its last reading as `cpu.<instance>`
(`share` 0..1, `cores`), each time it reads Dagu (every 30 s), so the scheduler and every worker count.

### Settings reference

The board adapters, `[scheduler]`, `[analytics]`, `[search]`, `[project]` and `[cursor_context]` are described by the examples above and
by [Scheduler](#scheduler); `[level]` by the flow graph it draws. Every other setting is described below, generated from the
models in `starpulse/runtime/config_model.py`, which the loader takes its keys and defaults from: edit a description there, run
`python -m starpulse.runtime.config_reference`, and commit the result. CI fails when this section differs from the models.

<!-- config-reference:begin (generated by `python -m starpulse.runtime.config_reference`; edit the Field descriptions in starpulse/runtime/config_model.py) -->

#### Top level

- `tracker_url` (text): The tracker's web address: a task links to `<tracker_url>/tasks/<id>`. Unset, it opens in the page's own Kanban.
- `database_url` (text): The SQLAlchemy URL of the history store; unset, `starpulse-history.sqlite` beside the config. The credentials never live here; they come from the driver's environment, such as `PGPASSWORD`.
- `event_log_retention_days` (whole number, 1 or more, default `7`): How long `serve` keeps the event log's rows: it prunes older ones at start and hourly, so the table, a SQLite file and every reader's replay at boot stay bounded. A reader that was down longer than this resumes at the oldest kept row and records the span it missed in `starpulse_gaps`. A whole number of days.
- `event_log_archive_dir` (text, default `"starpulse-archive"`): Where `serve`'s History child writes each row it prunes, before it deletes the row (see Event log archive): a directory, relative to this file unless absolute.
- `telemetry_loki_url` (text): The Loki base URL the harness adapters push each telemetry signal to, one log line per signal in `{job="starpulse-signals"}`, and the analytics views read back. Unset, the signals go to the event log. Give the stream its own Loki `retention_stream` rule to keep it as long as the event log.
- `slow_read_seconds` (number, above 0, default `1.0`): The seconds a `GET /api/pulls` or `GET /api/task/<id>` read may take, from accept to the last byte written, before `serve` logs a `slow_read` line for it: `queue_s`, `compute_s` and `write_s`, the seconds it waited for a handler thread, computed its answer and wrote it, `in_flight`, the reads of the same route running when it began, and `busy` and `streams`, the request workers in use (the read itself included) and the streams open when it was accepted. No other route is timed.
- `worker_memory` (table of `[worker_memory.<context>]` table): The memory limits (proportional size on Linux, resident size on macOS) `serve` holds each worker child to, in megabytes (see Worker processes), set as `[worker_memory.<context>]` with either key left out. Past `soft_mb` it replaces the child, past `hard_mb` it kills and restarts it. Defaults, soft/hard: `pulls` 768/1536, `scheduler` 512/1024, `runs` 512/1024, `flow-metrics` 384/768, `search` 384/768, `board` 768/1536, `dagu` 384/768, `github-actions` 256/512, `systemd` 256/512, `temporal` 256/512.
- `mode` (`"ic"`, default `"ic"`): `ic`, the one value: one person on one machine.
- `host` (text, default `"127.0.0.1"`): The address `serve` and `worker api` listen on; the default answers this machine only, and `0.0.0.0` answers the network. The `--host` flag overrides it.
- `port` (whole number, 1 or more, default `8766`): The port `serve` listens on. The `--port` flag overrides it.
- `hours` (number, above 0, default `6.0`): How far back a task's latest move on a machine counts; Admin's override replaces it. The `--hours` flag overrides it.
- `tls_cert` (text): The TLS certificate, relative to this file's directory; set with `tls_key`, else both unset.
- `tls_key` (text): The TLS private key, relative to this file's directory; set with `tls_cert`.
- `session_start_url` (text): The session-start service a started task is sent to (`POST <url>/start/TASK-N?harness=&mode=`); unset: nothing can be started.
- `harnesses_file` (text): A file, relative to this one, that declares the tiers and per-harness models.
- `pull_requests` (true or false, default `true`): With `gh` on the PATH, `serve` keeps a pull request store, current from the lifecycle events, that `/api/pulls`, the `ci` trail and `[release]` read. false never updates it: no event is applied, `POST /api/pulls/refresh` answers 404, tasks carry no PR state, and `/api/pulls` answers only from rows the database already holds. Set it on a second instance beside one that reads the same repositories, so one store is kept.
- `refresh_token_env` (text): Lets a producer that just saw a pull request close have its record read now instead of at the next minute's refresh: `POST /api/pulls/refresh` with `{"repo": "<owner>/<name>", "number": 12}` and `Authorization: Bearer <token>`. The PR store's thread reads that pull request alone (one single-PR GraphQL read, no listing) and publishes it as a refresh does; one asked for during a refresh is read after the repository in hand, ahead of that refresh's projection. The minute's refresh stays the fallback. 202 queued; 401 for a missing or wrong token; 403 for a repository this instance does not track; 400 for any other body. The value is the name of an environment variable, never the token; unset, or with no `gh` on the PATH, the route answers 404, and a named variable that is empty stops `serve`.
- `github_token_env` (text): The name of an environment variable holding a GitHub token. `serve` exports its value as `GITHUB_TOKEN` and `GH_TOKEN` before it starts any worker, so the GitHub reads and the child processes sign in with it; unset, or naming an unset variable, leaves both as they were. The value is the name, never the token.
- `take_over_command` (list of text): The command `POST /api/take-over` runs, as an argv: StarPulse appends the task id (`{"task": "TASK-7"}` in the body) and the command asks the task's workflow engine to flip that task's workflow to interactive, so it types nothing more into the task's session. Exit 0: sent (200). Exit 1: the task has no running workflow (409). Any other exit: an error, with the command's stderr. 404 when this is unset. The command is the only place a workflow engine appears.
- `runs` (list of `[[runs]]` table): One instance of a runs adapter per `[[runs]]` table.
- `producers` (list of `[[producers]]` table): A system that posts machine events as CloudEvents (see docs/sources.md, Post machine events as CloudEvents). `POST /api/machine-events` and the gRPC `starpulse.v1.CloudEventsIngest` answer 404 until one is declared. A producer writes only the machines and actors listed here.
- `repos` (list of `[[repos]]` table): A repository whose merges apply through the parent's pin bump rather than a run of their own.
- `ci` (`[ci]` table): Draws each task's pull-request CI as a sub-flow of these Board states.
- `release` (`[release]` table): Releases Waiting tasks natively. With the table present, `serve` moves a Waiting task to Ready once every task it depends on is Done (see Release); with no `[release]` table it releases none. The board must edit tasks and draw `waiting` and `ready` lanes, else `serve` refuses to start.
- `board` (table): The board adapter: `type` names a module under `starpulse` or the dotted path of one an installed package provides, and the rest of the table is that adapter's settings, shown in the Board examples above. With no `[board]` table the view draws its own Markdown board, `type = "native"`.
- `level` (table): The flow graph drawn above the Board (`starpulse.flow_metrics.model.level`).
- `scheduler` (table): The scheduler's policy; every key is optional (see Scheduler).
- `analytics` (table): What harness telemetry is read against for missed skill loads and trace clusters (see docs/sources.md).
- `search` (table): Ranks search by meaning as well as by words (see `search` in docs/cli.md).
- `project` (table): The project's own command line for each step a shipped skill names.
- `sequences` (table of list of text): The phases a task goes through, in order, keyed by task type (`story`, `bug`), with `default` for a type it does not name. A lifecycle machine link that lists `routes` sends a task to the route its sequence names next.
- `cursor_context` (table): Holds Cursor task sessions to a context limit (see docs/sources.md).
- `read_model` (any value, retired): Retired: the read model is the only board reader; accepted so a config that still names it loads.

#### [ci]

- `states` (list of text, required): The Board state ids the shipped `ci` machine is attached to as a sub-flow; one the Board lacks is refused. StarPulse ships one `ci` machine, which GitHub moves and StarPulse only observes (its `source` is GitHub). With `gh` available, each task with a PR is one agent in that flow, and its trail is the PR's pushes, check results, re-runs, conflicts, rebases and merge, read from GitHub every minute and kept in the event log (`machine:events`).

#### [[producers]]

- `name` (text, required): The CloudEvents `source` its events carry; unique.
- `token_env` (text, required): The environment variable holding its bearer token, never the token; no two producers share one.
- `machines` (list of text): The drawn machines it may write; leave out with `actors` for a producer that only reports runs.
- `actors` (list of text): The actors it may write as.
- `adapter` (text): A run adapter type whose own status labels its Step events carry, read through that adapter's `status_of`.

#### [release]

- `settle` (`"pin-bump"` or `"release"`): When a dependency counts as settled; left out, it settles when its task is Done. `pin-bump`: a dependency citing a pull request in a `[[repos]]` repository settles only once the parent pins its merge commit. `release`: a dependency citing a pull request in `repo` settles only once the running build contains its merge commit.
- `repo` (text): `settle = "release"` only: the repository the running build is released from.

#### [[repos]]

- `name` (text, required): The repository as its pull request links spell it.
- `path` (text, required): Where the parent holds the repository as a submodule: relative, inside the parent.
- `applied_by` (`"pin-bump"`, required): How its merges are applied; only `pin-bump`.

#### [runs.commit]

- `after` (text): The merge commit the run applies: pairs the run with that merge.
- `before` (text): The commit before it.
- `force` (text): The parameter that marks a forced run.
- `task` (text): The task a run is for: pairs a run with a task's entry into a lane (any Board event but MERGED).

#### [[runs]]

- `name` (text, required): The instance's name, unique; its workflows are drawn as `<name>/<workflow>`.
- `type` (text, required): The runs adapter: a module under `starpulse` or the dotted path of one an installed package provides. It offers `start(url)` and `follow(url, runs, log)`, and optionally `rerun(url)` and `declared_params(url, workflow)`, the parameter names a workflow declares, which `doctor` reads. See Runs adapters for what a built-in adapter reads and serves.
- `url` (text, required): What the adapter reads. A built-in adapter is an opt-in worker: you run `starpulse worker <adapter> --config <this file>` (`serve` starts it as a child), and, with it down or not yet started, the page shows this instance with the error "the <adapter> worker has not reported" or "last reported Ns ago" (its beat is older than 60s).
- `run_safe` (list of text): The workflows the page's Run now may start.
- `domains` (table of list of text or table of list of text): How the page groups this instance's workflows: each domain is a list of workflow names, or a table of process name to workflow list.
- `commit` (`[runs.commit]` table): The run parameters that carry what a run applies, so the Ledger pairs a run with its merge for certain. Each key names a parameter; a key left out is a parameter this instance has none of.

#### [worker_memory.<context>]

- `soft_mb` (whole number, 1 or more): Past this the child is replaced: a new one starts, then the old one stops.
- `hard_mb` (whole number, 1 or more): Past this the child is killed and restarted. Above `soft_mb`.

<!-- config-reference:end -->

## Scheduler

The scheduler is a switch, a capacity reading, an admission rule and a loop that acts on the rule. The switch is persisted in
the `scheduler.enabled` row of the history store's `starpulse_settings` table, so it survives a restart, and it starts off. A missing row,
an unreadable store or a malformed value reads as off. `[scheduler] state_dir` (relative to the config file) is where `starpulse migrate` looks for the older
state files. The toggle file of that older name (`TOGGLE_FILE` in `scheduler/model/toggle.py`) beside the config or in `state_dir` is imported once by `starpulse migrate`, keeping its modification
time as the row's `updated_at` (a row the store already holds wins), then renamed to the same name plus `.imported`.

`GET /api/scheduler` answers any address:

```json
{
  "enabled": false,
  "harness": "claude",
  "quietHours": {"start": "22:00", "end": "07:00", "timezone": "America/Phoenix"},
  "sampledAt": 1788307200.5,
  "dimensions": [{"name": "cpu", "use": 35.0, "limit": 80.0}],
  "inFlight": [{"task": "TASK-1", "title": "First", "model": "@agent-standard-high", "started": 1788307000.0, "url": "https://claude.ai/code/session_01"}],
  "next": {"task": "TASK-2", "title": "Second", "verdict": "waits", "reason": "cpu", "priority": "high/low"},
  "pauses": [{"harness": "claude", "until": 1788344400.0, "reason": "usage limit"}],
  "sessionsByHarness": {"claude": {"use": 1.0, "limit": 3.0}, "cursor": {"use": 0.0, "limit": 2.0}},
  "needsOperator": [{"task": "TASK-3", "title": "Choose the store"}]
}
```

`harness` is the harness the loop starts sessions on (default `claude`); `PUT /api/scheduler` with `{"harness": "<name>"}` selects another.
`quietHours` is the daily window in which the loop admits nothing, or `null` for none (see Quiet hours below).
`dimensions` lists `cpu`, `memory`, `sessions` and `review` in that order, each as its use against its limit; the
`sessions` meter follows the selected harness's cap: an Admin override if one is saved (see Session cap below), else
`[scheduler.session_limits]`, else `limits.sessions`.
`sessionCap` names that cap as `{"harness", "limit", "source", "configLimit"}`: `source` is `admin` for an override or
`starpulse.toml`, and `configLimit` is what the config sets.
`sessionsByHarness` names every harness's in-flight count against its own cap. A started session counts while its task
is In Progress or it has shown an event inside half an hour of its start; one at a prompt that never claimed its task
frees its slot. A credit or usage pause for one
harness lands in `pauses` and blocks admission for that harness only.
`sampledAt` is epoch seconds, and `dimensions` is empty with `sampledAt` null until the first sample.

- `cpu` and `memory` are the host's busy share and used share, in percent, read from `/proc`.
- `sessions` counts the tasks with an active harness session; with a dispatch loop it counts the selected harness's `inFlight` sessions that are active, so a session stopped between a reply and its next tool result frees its slot.
- `review` sums the `size-N` labels of the tasks in `review_lane`; a task without one counts `unsized_points`.

`inFlight`, `next`, `pauses` and `needsOperator` come from the dispatch loop, so a server that runs none leaves them out.

- `inFlight` lists every live session holding an In Progress task, oldest first, each with its task, title, agent
  profile, start time in epoch seconds and session address (`url`); it is `[]` when none runs. It includes the
  sessions `POST /api/start` or the operator opened, which have no known address (`url` is `""`) and count against the
  default harness's cap; a session is live while its harness machine has an event in the last 30 minutes, active or stopped,
  because every mid-turn reply stops the machine until the next tool result. A task whose assignee session wrote a transcript under `[board] transcripts` in the last 30 minutes is listed too when no harness
  row is on the task (a session opened on another branch keys its events there); it has no `url`, and is not counted against a cap.
- `next` is what the next pass would do, whatever the switch says: the task `decide` ranks first among those that fit, with
  `verdict` `starting` and `reason` `goes next`; when none fits, the top-ranked task with `verdict` `waits` and the first
  dimension it overfits as `reason`. Inside the quiet hours the top-ranked task `waits` with `reason` `quiet hours`,
  whatever room the host has. While a harness pause holds, it `waits` with `reason` `<harness> <pause reason>`, such as `<harness> usage limit`. It is
  `null` before the first sample or with no workable task in the eligible lane. Reading it logs no decision. Its `priority`
  names the Priority matrix cell the task ranked by (`high/low`, or `default`).
- `pauses` lists each harness whose admission is paused until `until` (epoch seconds) after a usage or credit-limit
  start, with `reason` `usage limit`, or an hour after a start halted on a missing binary, with `reason` `start halted: <the
  refusal, which names the path>`. The key is absent when none are paused.
- `needsOperator` lists the `kind-decide` tasks in the eligible lane, each with its task and title. Admission starts one
  last (see Fit and Order); its session frames the choice and parks for the operator's answer. It is `[]` when there
  are none.

`PUT /api/scheduler` with `{"enabled": true}` or `{"enabled": false}` sets the switch, and with
`{"quietHours": {"start": "HH:MM", "end": "HH:MM", "timezone": "<IANA zone>"}}` or `{"quietHours": null}` sets or clears
the quiet hours; `{"sessionCap": <whole number above zero>}` or `{"sessionCap": null}` sets or clears the selected
harness's session cap; a body may carry several. It answers the same body as the `GET`, and a body with anything wrong is a 400
that changes nothing. It answers only loopback and private-network (RFC 1918) addresses, with 403 elsewhere, and like every write it needs
`Content-Type: application/json`. A `serve` that runs no scheduler, an adapter-kit server, answers 404.

The sampler reads every 60 seconds. The first sample is a baseline; after it, a dimension going from below its limit
to at or over it, or back, logs one `StarPulse scheduler: <dimension> is full|free (<use> of <limit>)` line.

StarPulse Admin's Scheduler card shows it: the switch with **On** or **Paused**, a meter per dimension (amber from
80% of its limit, red past it, dimmed while the switch is off), the next pick as text (its task, title and `starting`
in green or `waits: <reason>` in yellow, or **Nothing eligible**), the count of sessions in flight (the Sessions
dimension's use, or the length of `inFlight` without it), the session cap row, and the quiet hours row. A click on the switch sends the
`PUT` with no dialog, and a refusal shows its reason under the switch. The card reads `next` from the same body when it
carries it, and shows no pick without it. It reads once when Admin opens and follows the `/api/events` `scheduler`
event after. A server with no scheduler (404) shows the card with its reason and no controls. The Kanban draws no
scheduler control.

### Session cap

The Scheduler card's **Session cap** row sets the selected harness's cap from StarPulse Admin, over `starpulse.toml`.
`PUT /api/scheduler {"sessionCap": 12}` keeps 12 for that harness in the history store (setting
`scheduler.session_caps`, one value per harness); `{"sessionCap": null}` clears it, and the config's cap applies again.
Anything but a whole number above zero is a 400 that changes the stored cap not at all. The admission loop reads the
override on every pass and a save wakes it, so a new cap takes effect with no restart; sessions already running past a
lowered cap continue and nothing new starts until the count falls under it. The override survives a restart. The
sampler's full/free log lines still read the configured limit.

### Quiet hours

The quiet hours are a daily window, from `start` up to but not including `end` on `timezone`'s wall clock, in which the
loop admits nothing; an `end` before the `start` runs past midnight. Sessions already running continue, and the loop
still finishes and settles them: only admission stops, as with the switch off. The window is the `scheduler.quiet_hours`
row of `starpulse_settings`, so it survives a restart; no row, or one that cannot be read, is no window. Setting it wakes
the loop, so a window that no longer covers now admits at once. There is no config key: the operator sets it from
StarPulse Admin, whose Scheduler card has a **Quiet hours** row (a switch, start and end times, and Save) that
sends the browser's own zone with the times.

### Admission

`scheduler.admission.decide` answers, for each workable task in the eligible lane, whether it fits and where it ranks. It is
a pure function of the open tasks, the sampler's readings, the `[scheduler]` policy, the trajectory chain, each task's
forecast P(goal), and the run ledger.

- **Demand.** A task draws `size points x its tier's weight` percent of CPU and of memory, one session, and its points of
  review. The tier is the middle word of its profile (`@agent-standard-high` is `standard`); a tier with no weight, or no
  profile, prices at the dearest weight. Once 3 runs of the same tier and size are in the ledger, their mean peak replaces
  that prior.
- **Fit.** A task whose profile names no tier with a weight is refused as `no agent profile`, since its session would
  run on whatever model the harness defaults to. Any other task is admitted only if its demand is at most the headroom
  (limit less use) on every dimension; otherwise the decision names the first dimension it overfits. A task labelled
  `kind-decide` fits against the headroom less the demand of every other admitted task, so it never takes room a
  mitigation, bug or story task needs.
- **Order.** The admitted tasks go first by class: the tasks labelled `regression`, then a bug another open task waits on,
  then the other bugs (type `bug`, or labelled `board-state` or `regression`), then the tasks labelled `leverage`, then the rest, then the `kind-decide` tasks. Within a class they go by
  the most open tasks waiting on them directly, then the deepest critical path (the task itself plus the longest chain
  of open tasks waiting on it), then the heaviest Priority weight, the lowest id breaking a tie. The weight is the `[scheduler.priority_matrix]`
  cell of the task's `<impact>/<urgency>` (`high/low`), 1 to 9 by default as the product of the two levels' places
  (low 1, medium 2, high 3); a task missing either field ranks under `default`, 4. In shadow, the default, a second order
  is only logged: `value / dominant share`, where value is weight times depth times P(goal) and dominant share is the largest `demand / limit` over the dimensions. P(goal) is the task's forecast
  chance of the goal in the eligible lane (`trajectory_analytics(...)["forecast"]`), else the chain's `p_goal` for that
  lane, and 1 when the lane has no history. The loop reads those ranks whenever `[level]` is set. An optional predictor, a
  function from a task's title and description to a score, replaces P(goal) in that shadow value and is logged; a
  predictor that raises leaves the score empty.
- **Log.** Each decision logs one line:
  `StarPulse scheduler: <task> admitted|refused (<dimension> full|no agent profile) p_goal=<p> predictor=<score> shadow_rank=<n> enforced_rank=<n>`.
  Ranks number the admitted tasks from 1; a refused task has none.

The run ledger is the history store's `starpulse_scheduler_runs` table (migration 0016, renamed by 0028), one row per finished run: its task, tier,
points, outcome, duration in seconds, the peak demand it drew on each dimension and the epoch second it was recorded. Event-log pruning never deletes
it, and the store's snapshot carries it. The ledger file of that older name (`LEDGER_FILE` in `scheduler/model/ledger.py`) in `state_dir` when set, else beside the config, is imported by `starpulse migrate`
once into an empty table, each run stamped with the file's modification time, then renamed to the same name plus `.imported`. While
the store cannot be read the ledger measures nothing, so admission prices every task at its declared demand.

### Dispatch

While the switch is on, the loop calls `decide` and starts the admitted tasks. A task a post-merge QA miss sent back to
`in_progress` (it carries the `regression` label) with no live session counts as eligible-lane work, so it is picked and
ranked first; once its run ends it is held until the task leaves `in_progress`. The loop runs on events, never on a dispatch timer:

- a task enters the eligible lane (or a task there becomes workable), or enters `in_progress` labelled `regression`;
- a harness session stops, or a started task changes;
- the switch turns on;
- the sampler's reading of a dimension crosses its limit;
- the feed's `scheduler` status event of a new sample says the next pick would start: a task's demand can fit a
  dimension's headroom without the dimension ever having reached its limit, so a crossing alone would leave it waiting.
  The loop reads that event from the feed it already subscribes to (the stream `/api/events` serves), once per sample.

Each pass starts the first admitted task, then decides again over readings that carry that task's demand, so two tasks that
do not fit together are never both started in one pass. A run holds its capacity from its start until its task leaves
`in_progress`; until the harness reports the session active the loop adds that demand to the sampler's readings itself.
A start that fails (`StartFailedError`) is logged and its task skipped for a backoff of 30 seconds that doubles with
each further failure, up to 30 minutes, unless the refusal names a usage or credit limit: admission for that harness then
pauses until the reset clock the message names (or five hours when it names none), `GET /api/scheduler` lists it under
`pauses`, and the next pick `waits` with `reason` `<harness> usage limit`. A refusal that names a missing binary
(`the starpulse binary is missing: <path>`, `needs <binary> on PATH`) fails again until the host changes, so it halts
admission for that harness for an hour after the first occurrence: one `ERROR` journal line names the refusal and path, `pauses`
lists it with `reason` `start halted: <refusal>`, and one start tries again when the hour ends. A start that succeeds comments
`Scheduler started <task>: <session address>` on the task; a board that refuses the comment leaves the session started.

A session starts through `session_start_url` when the config sets it; the loop's request is
`POST <url>/start/<task>?harness=<selected harness>&mode=interactive&by=scheduler`, so the service can brief an unattended session
unlike one an operator opened (an operator's start has no `by`, and the page's `POST /api/start` body names `harness` with
`mode` defaulting to `interactive`). With none, the built-in starter runs
`tmux new-session -d -s starpulse-<task> -c <config directory> claude --remote-control <task> "Start <task>"` and needs
`tmux` and `claude` on `PATH`, so a board with no `[scheduler]` table and no `session_start_url` starts a task out of the
box. The built-in starter starts only Claude: with another harness selected it refuses the start, naming
`session_start_url`, and ignores `mode`.

When a run's task leaves the eligible lane and `in_progress`, the loop writes its outcome (the lane it went to), duration and
peak to the ledger. When the harness session stops while the task is still in those lanes, the run is written as
`session-ended` and the task is held out of admission until a person or the sweep moves it; a later tool or start on the
same session revives that run instead of starting another. A started session that has been idle longer than
`idle_minutes` (the harness's last active event, or its start before any) with its task still open is returned once to the
eligible lane with a comment, when the task cites no pull request (the run is written `idle-returned`, and the task's count
is kept under `scheduler.idle_returns`). Any other idle session is settled once: the task moves to `needs_attention` with a
comment saying why and is never started again; so is an idle session of a task already returned once, or one that cites a
pull request. A board with no editor, or no `needs_attention` lane, refuses the move; the loop logs the
refusal and retries on the next sampler period. The sampler period (60 seconds) is the only timer; it finishes and settles
runs and never admits.

The runs in flight, each task's last start time and the last capacity sample live in `starpulse_worker_state`
(`scheduler.inflight`, `scheduler.starts`, `scheduler.sample`), so a restart restores them: `GET /api/scheduler` still
lists the sessions, the loop still settles and records them, and a task it already started is not started again. A restart
logs `StarPulse scheduler: restored N in-flight`. A start still inside 15 minutes (`START_COOLDOWN`) is not admitted
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
  merge commit as the proof in the edit's comment. A record that says merged with no merge time (an event's word, not
  a read of GitHub) is not terminal until the store's next read settles it.
- `pr_merged`: `pr_terminal` holds, at least one cited pull request merged, and the task's record carries no Verify
  plan (`verifyPlan`, read through `Board.read`; a board with no reader has none), so a task whose every pull request
  closed unmerged stays. A state that parks work for a person may declare `waits: {pr_merged: MERGED}` to close a task
  whose delivery merged while it waited there.
- `pr_closed_unmerged`: `pr_terminal` holds and no cited pull request merged. A state that waits on it, with the event
  moving to Needs attention, parks the task there with the closed pull requests and a question to the operator as the
  `## Needs attention` reason, as `overdue` does.
- `pr_closed_unmerged_complete`: `pr_closed_unmerged` holds and every acceptance criterion and Definition of Done item is
  checked, so a no-op task has nothing to ask. A state that waits on it may declare an event that closes the task.
- `pr_merged_planned`: `pr_merged` without the plan condition, and the record carries a non-empty Verify plan. A state
  lists it before `pr_merged` to route a merge by plan, as in `waits: {pr_merged_planned: MERGED_VERIFY, pr_merged:
  MERGED}`: a planned task takes `MERGED_VERIFY`, an unplanned one `MERGED`. A read of the record that raises holds
  neither until the task is derived again.
- `pr_merged_unfinished`: `pr_merged` holds and the board's `unfinished` command prints a non-empty JSON array of the
  work the merge leaves, so a task whose planned pull request in another repo never opened does not close. The edit's
  comment names the merge proof and the work left. A state lists it before `pr_merged` and maps it to a move into
  Ready. With no `unfinished` command, or an empty array, it never holds. A command that fails or prints no array
  holds it, with the error as the work left: a task is not closed on a board that cannot say what is unfinished.
- `pr_ready`: the task cites a pull request and any cited one is merged (with a merge time) or open and not a draft.
  The edit's comment names the ready and merged pull requests as the evidence. A state may declare
  `waits: {pr_ready: REVIEW}` to move its tasks to Review once a pull request is ready.
  A task moved from `review` to its working lane holds, for each pull request it cites, the head it was moved on: an open
  pull request still on that head is the reviewed work, so the fact does not hold for it until a push changes the head
  or the lane changes (the actor remembers it in memory only, so a restart clears it).
- `pr_failing`: any pull request the task cites as its own delivery is open with a failing required-check rollup
  (`checks` is `failing`). The comment names the pull requests and ends in a question, which is also the
  task's `## Needs attention` reason. A state may declare `waits: {pr_failing: DEMOTE}`.
- `pr_draft`: any pull request the task cites as its own delivery is open and a draft. A state may declare
  `waits: {pr_draft: SEND_BACK}` to return its tasks to the working lane, which runs the board's `returned` command.
- `pr_conflicting`: any pull request the task cites as its own delivery is open and conflicts with its base. The same
  `SEND_BACK` move serves it.
- `deps_done`: the task has dependencies, every one is Done, its description declares no Start Criteria, and, under
  `[release] settle = "pin-bump"`, every dependency's pin bump has merged (the rule in Release).
- `deps_done_with_pr`: `deps_done` holds and `pr_ready` holds (the task cites a ready or merged pull request). A state lists it before `deps_done` to
  return a task that has a delivery to another lane than the one a task without one returns to.
- `deps_unresolved`: a dependency is not Done.
- `criteria_met`: the task's Start Criteria were last evaluated all `met`.
- `criteria_unmet`: a Start Criterion was last evaluated `unmet` or `error`.
- `overdue`: a Waiting task is past its service level expectation: seven days from the lane's `entered` time, or
  two days past the latest `expect_by` its Start Criteria declare (an ISO date or timestamp; one with no zone is UTC).
  A task gated only on dependencies is exempt while every open dependency is in the working or review lane. A state
  lists it last, so a gate that holds wins, and maps it to a move into the attention lane; the actor sets the task's
  `## Needs attention` section to the age, the SLE and the gate, ending in a question. A lane that waits on it also gets
  a deadline thread: each derivation arms the task's deadline, and the thread derives the task again when it falls, so
  no event has to wake it. A re-park, a new `expect_by` or a dependency's lane change re-arms it. A task whose Start
  Criteria are not yet read is not overdue until they are.

A lifecycle machine whose phase state links a skill machine with `exits` (`submachines[].exits`, [Public surface](public-surface.md))
advances too. When the skill machine of the task's current phase reaches a state its link exits on, the actor publishes
the exit's event for that machine to `machine:events` as `starpulse/task-actor`, once per visit to the phase. A skill
machine the current phase does not link advances nothing, so a late final event of an earlier phase's skill cannot move
the task. The machine's `writers` name `starpulse/task-actor` for each such event.

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

A park that names `TASK-X#K` records the criterion the dependent needs (`dependency_needs`). A dependee's state change or
a criterion it checks re-derives its dependents. Once every criterion a dependent needs of an open dependency is checked,
that dependency counts as met: `deps_done` fires, and the release is one write that drops the dependency and its needs and
comments `Stale dependency TASK-X`. A lint refusal of the release is commented once on the task (a comment-only edit skips
the board's guards, so the comment lands) and the actor retries when the lint record changes.

A move from the working lane (the first resting State the lifecycle does not end in) to Waiting runs the board's
`parked` command once, with `{id}` replaced by the task's id, so a board can tell the session that holds the task. A
move from Waiting to Ready runs the board's `released` command the same way, so a board can resume the session that
parked the task. A move whose last event is `DELIVER_FINISHED`, the machine event a delivery run publishes when it
ends, runs the board's `delivered` command once per run, with `{id}` and `{verdict}` (the event's `verdict` and `step`,
such as `red test`) replaced, so a board can resume the session that holds the task on the verdict. A move from Review back to the working lane runs the board's `returned` command the same way, so a board can wake the session that delivered a pull request that turned draft or conflicting. A move to Done runs the board's `closed` command once the same way, so a board can file what follows the close, such as a
check that waits on time after the merge. A command that exits nonzero is logged; the move stands.

A write the board refuses is logged and counted, and is not retried until the task's facts change; checking the last
Definition of Done item of a task (`definition_of_done` in its record) is such a change, so a Done move a guard refused
for an unchecked item is tried again. A release to Ready
that a declared guard or the `validate` hook refuses is a defect in the task record: the task stays in its lane with a
comment naming the refusal, no operator question is minted, and the actor retries once the task's description, profile,
labels or dependencies change. `GET /metrics` carries:

- `starpulse_task_actor_refusals_total`: refused writes.
- `starpulse_task_actor_latency_seconds`: a histogram of the seconds from the fact being observed to the write landing.
- `starpulse_task_actor_projection_seconds`: a histogram of the seconds each projection of the pull request store ran,
  the pin walk included.
- `starpulse_task_actor_handoff_seconds`: a histogram of the seconds from a store save to the actor reading it. The
  bounds run to 600 s, so a handoff or projection past the 10 s bound shows.
- `starpulse_task_actor_criteria_errors{task}`: the Start Criteria of a gated task that could not be evaluated; such a
  gate never passes.
- `starpulse_task_actor_pin_held`: a gauge of Waiting tasks whose dependencies are done but wait for a pin bump to
  merge (`PinGate.waiting_on`); one that stays above 0 is a pin that never merges. Each such hold comments the pull request
  and pin it waits on once. Only a cited pull request that can be the dependency's own delivery counts: one whose
  branch or title names another task is a reference.

Each move the actor writes names `starpulse/task-actor` on its `board:lanes` entry: the Delivery worker records the lane
change when it writes it, in the history and the log in one transaction, and the file scan that places the change
later finds the lane recorded. The same holds for every write `serve` makes on the native board, under the request's
actor. A change no such write recorded (a file edited by hand, a board adapter whose writer does not say the lane it
set) is recorded at its placement as `external`. `GET /metrics` carries `starpulse_board_lane_unattributed_total`, a
counter of the `board:lanes` entries any process appended since `serve` started that name no actor.


## Conformance violations

`serve` judges every move against the machine that draws it, as `starpulse conform` ([Replaying history against the
machines](cli.md#replaying-history-against-the-machines)) does on the stored history, and `GET /metrics` carries two
counters for each machine the feed draws:

- `starpulse_machine_conformance_events_total{machine}`: the moves judged.
- `starpulse_machine_conformance_violations_total{machine}`: the moves no transition declares.

The `board` machine is judged on `board:lanes`, every other machine on `machine:events`. `serve` counts every entry
the log still retains and follows new ones after, so a restart recounts the retained entries rather than starting at 0,
and an entry pruned from the log leaves the count. The count of retained entries runs on a background thread, so the
banner does not wait on it: until it finishes, a scrape shows the counts so far. Every machine has both series from the
first scrape, at 0 until a move arrives. The first lane seen for a task is placed unjudged, because the log keeps no
earlier history; the stored-history replay judges it from the initial state. Guards are not judged.

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

A task is hot until local midnight after it enters `done`, then cold: the board feed holds only its `id`, `state` and
`entered` time, and `GET /api/snapshot` omits it. A hot task keeps its record in `flows`; a lane change out of `done`
(a reopen) reloads the cold task from its board file onto its new lane within that one change, and cooling itself
publishes nothing, so a page keeps a card until it reloads. The page's snapshot (`/api/snapshot`) is slim:

- `flows` carries open and hot done tasks, each without `description` and `criteria` (read them from
  `GET /api/task/<id>`) except an In Progress task, which keeps both live; each has its `moves` as `move_set`, a key into
  the snapshot's `move_sets`;
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

`starpulse init [--dir DIR] [--harness claude-code]` scaffolds a first install: `starpulse.toml` (a native `[board]` with
one `[[board.guards]]` rule, a `[scheduler]` table and a `[[producers]]` entry reading `STARPULSE_TOKEN`), `board.yaml`
(four States, every role declared) and the harness's telemetry settings (`.claude/settings.json`). It never writes a
token, and writes nothing, naming the file on stderr and exiting 1, when any of the files exists.

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
