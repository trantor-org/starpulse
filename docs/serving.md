# Serve and configure

## Serve

Open <http://localhost:8766>. The first serve creates `.starpulse/board/` in the working directory (beside the config file when `--config`
names one): a `config.yml`
holding the project name (that directory's name, the team its tasks are in), the lanes (To Do, In Progress, Done) and an empty `tasks/` directory, one Markdown file per task. The
Kanban view starts with no tasks: **New task**, at the top right beside the task count, opens a form for its title, description, priority, impact, urgency, labels,
milestone, assignee, dependencies and acceptance criteria and adds it to the first column. The `starpulse` verbs, `task create`
among them, are written for an agent to run ([the Agent CLI](cli.md)) and work the same typed by hand; the page and the verbs write the
same board. While a board that can create tasks (the native one) has none, the Star Map says so under the breadcrumb, naming `uvx starpulse task create "My first task"`
and **New task** as the two ways to add one. StarPulse keeps its event log and history in
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
file that is not there, stops `serve` at start with the reason. With neither, the port is cleartext and sends no `alt-svc`. A change to either key, or to the bytes of either file (a renewed
certificate written in place), replaces the Page API child on `starpulse reload` beside the old one on the same socket, with no `serve` restart and no dropped connection; a renewal hook runs `starpulse reload`. A reload that cannot read either file changes nothing and fails naming it. A client's certificate trust is its own, so `curl --cacert <cert>` or a browser that trusts the certificate reaches the HTTPS and HTTP/3 port.

The handlers are blocking, so each request runs on a pooled worker thread (`REQUEST_THREADS`, 128, the listen backlog)
and a crowd of pages queues for a worker rather than starting a thread each, until every worker is busy: the admission
middleware then answers any request, whatever its route, `503` with `Retry-After: 1` before a route sees it (the Connect
ingest path, which has its own token, is outside it). The pooled workers keep the default thread
stack size, where the previous server gave them 256 KiB: the free-threaded build's RSS check (`test_crowd_rss.py`) runs
only on 3.15t. On that build mimalloc keeps freed pages resident until its purge delay lapses (3.6 GB resident
against about 1 GB live in one deployment, 1.5-1.7 GB with no delay), so `serve` sets `MIMALLOC_PURGE_DELAY=0` in every
child it supervises unless its own environment already names a value, which the child keeps.

A subscription (`POST /graphql` answered as `text/event-stream`) leaves that pool for as long as it stays open and is counted
against `STREAM_LIMIT` (256) instead, so a crowd of long-lived subscriptions never takes the worker a short request needs. A
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
holds a Task, an encoded snapshot or its gzip between requests.

A stopping server first tells the feed it is restarting, ends every open stream, waits up to 8 s (`DRAIN_S`) for the
requests it took and closes.

### Worker processes

`serve` is a supervisor over two children, each a `starpulse worker <name>` process: `api` (the Page API) and `contexts`, the one process that runs every background context as a thread: `pulls` (Delivery), `scheduler`, `runs` with each run adapter a `[[runs]]` instance names (`github-actions`, `systemd`, `temporal`), `flow-metrics`, `signal-folds` (the per-session folds of the harness signals the per-task spend route and the sessions sink read), `lane-metrics` (the unattributed-lane count, the conformance monitor and the lane sweep, whose metrics text the Page API relays), `search` (with an `[search] embeddings_url`) and `board` (the Start Criteria dating). `serve` starts each as a child, restarts it with a growing delay (1 s, doubling to 60 s; a child that ran a minute restarts at once) when it exits, and stops it when `serve` stops on `SIGTERM` or Ctrl-C. The children read the same config and `database_url` and meet `serve` only in the event log. No unit file is needed to run StarPulse, and no setting turns a child off: `starpulse reload` picks the children whose code or config moved. The set of children does not depend on the config: a config naming every run adapter still has two.

The `api` child serves the page and the HTTP API. `serve` binds `--host` and `--port` once (or adopts the socket the service manager passes in), keeps that listening socket for the life of the process and starts `starpulse worker api` with it on the descriptor named by `STARPULSE_LISTEN_FD`. `serve` first builds the page's machines and board from the config and exits 1 with the reason when it cannot, so a bad `starpulse.toml` or `board.yaml` stops `serve` rather than a child that exits at every start; the child serves the page build of the release it runs from (`STARPULSE_STATIC` names another directory, as a test's stub page), so a reload after a merge that rebuilds the page serves the new build. The child reads the Board from the read model the `contexts` child folds and starts no adapter watcher. A reload of the child starts the new one on the same socket, waits until it reports (`STARPULSE_READY_FD`) it is about to serve, or 30 s (`warm`) at most, then stops the old: the old one stops accepting, finishes its in-flight requests (up to 8 s) and exits, so a connection made meanwhile queues in the backlog and none is refused. The child serves the snapshot the Board writer stored and builds none, so a connection that queued across a restart or a reload is answered from the store, never by a build in its request (a 503 with `Retry-After: 1` before the writer has stored one); an agent client (`starpulse` verbs) sends a GET once more when the server answered it with an empty reply.

The background contexts share one process so the interpreter, the imports and the database stack are paid for once, not once per context. A context that fails stops its thread alone and is restarted in place; a config-only reload sends the `contexts` child `SIGHUP` and it re-reads the changed context's settings under the same pid, while a change to code any context runs, or to a setting a context cannot take in place, replaces the child.

Every child is a `subprocess` child with its own imports, on every platform, and still dies with `serve`: it holds the read end of a stdin pipe `serve` keeps the write end of. The Page API child inherits `serve`'s listening socket and the `contexts` child the GitHub webhook socket.

`starpulse reload` replaces the children whose installed code or Board machine file (`[board] machine`, by content hash) changed, tells the `contexts` child whose only change is a live config block to re-read it, and re-executes `serve` when its own code changed, handing every child whose own closure and config did not change to the new `serve` by pid and stdin pipe, so a deploy restarts only what it changed: a `serve`-only change never ends the `contexts` worker. See [Reloading a running serve](cli.md#reloading-a-running-serve).

`serve` also holds each child to a memory limit, sampled every 5 s. Past the soft limit it replaces the child: the old one is stopped (killed after 10 s if it ignores `SIGTERM`), then the new one starts, so the new one finds the ports and leases the old one held free; the Page API alone starts its replacement beside it, on the shared socket. Past the hard limit it kills the child and starts a new one at once. Each action is logged as a warning naming the context, pid, size and limit. The size is the proportional set size on Linux (`Pss`, which divides each page processes share among the processes that map it) and the resident size on macOS, read with psutil; where there is no reader, as on Windows, `serve` logs one warning and runs the children without limits.

| Child | `soft_mb` | `hard_mb` |
| --- | --- | --- |
| `api` | 4096 | 8192 |
| `contexts` | 1536 | 3072 |

`[worker_memory.api]` and `[worker_memory.contexts]` override either key for a child (whole megabytes, 1 or more; `soft_mb` below `hard_mb`). An unknown child, an unknown key or a soft limit not below the hard one is refused at load by name, and so is a per-context key from before the contexts shared a process (`[worker_memory.pulls]`, `[worker_memory.scheduler]`, `[worker_memory.temporal]` and the rest): the message names `[worker_memory.contexts]` as the replacement. The `api` child holds the telemetry window and the read model, so its limit is set above the peak the deployment measures; Trantor's `starpulse.toml` does.

`GET /api/health` is the api child's readiness: each context stamps its start in the `ready` worker state with the boot
token `serve` handed it (`STARPULSE_BOOT`), so a stamp left by an earlier boot, or copied with a store, never counts.
`starpulse rehearse` reads it (see the CLI document).

### The NATS server

`serve` always supervises the Page API and the contexts worker; unless `[bridge] enabled = false` it supervises a third
child, `nats`, beside them (`starpulse/runtime/nats_server.py`), and `worker_memory` limits only the two workers. It
fetches the pinned `nats-server` release for the platform (Linux and macOS `.tar.gz`, Windows `.zip`), checks the archive
against the SHA-256 pinned beside the version in `nats_server.py`, and keeps the binary in the
user cache (`$XDG_CACHE_HOME/starpulse`, `~/Library/Caches/starpulse`, `%LOCALAPPDATA%\starpulse`) beside the digest it was
verified as. It runs on `127.0.0.1:<port>` only, with JetStream on and its store in `store_dir`; the supervisor restarts
it on exit, and it stops with `serve`. A download that fails its checksum, or a cached binary that no longer matches its
digest, starts no server: the child exits naming the two digests and is retried with backoff. The first start needs
network access to GitHub for the download, so an offline install sets `[bridge] enabled = false`; then nothing starts
and nothing is fetched. A change to `[bridge]` restarts `serve`.

### The bridge

Unless `[bridge] enabled = false`, the `contexts` child also runs the bridge (`starpulse/bridge/`), which publishes the event
log to the NATS server above. It reads `board:lanes` and `machine:events` in log order from its own checkpoint, `bridge:nats`,
which it saves after each entry the server acknowledged; a restart resumes at the first entry not published. A first start
has no checkpoint and starts at the newest entry, so a subscriber is given the latest state and never the history. The
server being down, or its store deleted, only delays an entry: the bridge declares the stream `starpulse-<board>` again
(`starpulse.<board>.>`, file storage, the newest 100 messages per subject) and retries until the entry lands. Delivery is
at least once: each message carries its entry's event id as `Nats-Msg-Id`, which the stream drops a repeat of within its
duplicate window, and a subscriber that must not act twice dedupes on the `event_id` in the body.

A subject is `starpulse.<board>.<entity>.<id>.<event>`, `<board>` being `[bridge] board`:

| Entry | Subject |
| --- | --- |
| `board:lanes` lane move | `starpulse.<board>.task.<task>.moved` |
| `machine:events` naming a pull request | `starpulse.<board>.pr.<number>.<event>` |
| `machine:events` of a task, no pull request | `starpulse.<board>.task.<task>.<event>` |

`<event>` is the machine event lowercased without a leading `PR_` (`PR_MERGED` and `MERGED` are both `merged`;
`CHECKS_FAILED` is `checks_failed`). A pull request number is the event's `data.pr`, else the `/pull/<n>` in the `ci`
machine's event id. A machine event of a run alone, and every other stream, is not published. A character of a token that
NATS reads as structure (`.`, `*`, `>`, a space) becomes `_`. The body is JSON: `event_id`, `stream`, `at` and the entry's
`fields`.

The same thread keeps one durable consumer per session on the stream (`starpulse/bridge/consumers.py`), named for the
session (`--session`, else `STARPULSE_SESSION`, as a token) and starting from the newest message of each subject. Its filter
subjects are the session's subscription, and the origins of each subject ride in the consumer's metadata, so StarPulse
keeps no table of them. Three things add subjects:

- A move of a task: the session holding it (the task's assignee) gets the `claim` subjects of the `[bridge.subscriptions.<kind>]`
  table named for the task's `kind-*` label, with `{task}` the task id, and the `pr_opened` subjects of each pull
  request the task already cites, so a session claiming after its PR opened still hears its conflict. A session that took subjects from the task and
  no longer holds it, or whose task is done, completed or archived, drops them (a finished task keeps its assignee, so
  the lane decides). The bridge makes the same check for every task of every consumer once at start, so a consumer an
  older release left on a finished task's subjects loses them; a consumer left with none is
  deleted. A session whose process ended keeps its consumer while it holds a task, since the `resume` hook wakes it from it.
- A `PR_OPENED` machine event naming a task and a pull request: the holder gets the kind's `pr_opened` subjects, with
  `{task}` and `{pr}`.
- `starpulse subscribe <subject>...`, which asks the bridge to add full subjects in one consumer write under the `explicit` origin until `starpulse unsubscribe
  <subject>`; a task change leaves it alone. A subject written `incident.<type>.<key>` (or `incident.<type>.>`) is taken whole, not relative to the board.

A kind with no table, or a rule with no subject, subscribes to nothing. A session left with no subject has no consumer.
A subject in a rule is relative to the board and may not name `starpulse`; `serve` refuses a rule naming a value its
event does not know. `subscribe` and `unsubscribe` ask the running bridge on
`starpulse-bridge.<board>.subscription`, and the bridge applies the change under the same lock as its own grants, so it
alone writes a session's consumer; with no bridge running they exit unavailable.

#### Incidents

`starpulse incident open <type> <key>` tells the sessions of a shared fault, with no event in the log:
it publishes `incident.<type>.<key>` (each token as `subscribe` writes one) to the NATS server as a plain message, which
the bridge's one stream also keeps (it takes `incident.>` beside the board's own subjects, an existing stream gaining it at
the bridge's start), so it works while the board's API is down. When NATS does not answer (the server is `serve`'s child, so a stopped `serve`
takes it down too) the verb still succeeds with `published` false once it holds the owner task, and exits 3 only when
the board did not answer either. The owner task is the board's own: the verb
creates one filed under source `incident.<type>.<key>` and claims it, so a second finder finds the open task, holds
nothing and publishes nothing. While the board is down the publish goes out with `task` null and the verb leaves the
task to the finder's rerun, which creates it and publishes again with its id; a finder's rerun with its task already
made only publishes again. A task in the done state no longer holds the incident. `--failing-pull` narrows the tasks that wait to those with an open pull request whose checks read failing, and the incident's body names them as `parked`, so only their sessions are woken by it, never the rest of the reach.

The incident's type declares in `[bridge.incidents.<type>]` which sessions it reaches: the held tasks with any listed
`kinds` (`kind-*` label) and any listed `areas` (`area-*` label), in the working lane, the only one a task can wait from. A table must name at least one selector, and a type with no table reaches none. With the owner
task made or found, the verb parks each task in reach on it (`task park --until-task`), with a comment naming the
incident, so the session is told by the task's move on its consumer and by the comment; the task actor releases it when
the owner task is Done, as for any dependency. The owner task, the finder's own task and a task no session holds never
wait. The verb prints `waiting` (the tasks parked) and `refused` (each task the board refused, with its reason), and a
rerun parks the tasks that began since. A raw publish to the subject, with no verb, has no owner task.

The same reach subscribes the sessions to the incident: the bridge gives the holder of a working-lane task in a type's
reach the subject `incident.<type>.>` beside the task's own, and drops it when the task leaves the working lane or
finishes, so a session told of one incident is not woken by the next after it has moved on. The notifier posts one line,
`incident.<type>.<key>: task=<owner task> finder=<session> (<time>)`, and a session may also `subscribe` to one by hand. A consumer created after an incident was published, and a session of an incident whose owner task is done or archived, are delivered none.
An incident older than six hours is acked with no line, so a consumer first granted the subject is not woken by every
old key the stream still holds. The publish needs no API, but the line needs the bridge and the session's registration,
so a stopped `serve` delivers nothing and the finder's owner task is the record.

#### Notifying a session

`starpulse subscribe`, run by a Claude Code session, also registers how to reach it: the inbox socket and token the
harness gave its process (`CLAUDE_CODE_MESSAGING_SOCKET`, `CLAUDE_CODE_MESSAGING_TOKEN`) and its working directory, in an
owner-only file `starpulse-sessions/<session>.json` beside the config. The token never reaches NATS and no command prints
it. A session that never ran `subscribe` has no registration, is not notified, and keeps its events on its consumer; a
session subscribes explicitly to be woken, so a change reaches one session before any other.

Once a second the bridge lists the consumers with messages waiting and, for each registered session, fetches a batch and
notifies the session's harness (`starpulse/sessions/ports/notify.py`). Claude Code's adapter
(`starpulse/sessions/adapters/outbound/claude_code_notify.py`):

- posts one line per event, `<subject>: <event> <task> <data> (<event id>)` (the first 20 data pairs; every key and value
  loses `<`, `>` and line breaks and is cut at 120 characters, so none can close the envelope), to the session's inbox
  socket, wrapped in the
  `<cross-session-message from-mode="bypass">` envelope that Claude Code accepts from an attested sender in
  `bypassPermissions`. It posts to the socket of the running process the sessions directory
  (`$CLAUDE_CONFIG_DIR/sessions`, else `~/.claude/sessions`) names for the session id, else to the registered one;
- resumes a session whose process has ended, under the same session id, with `[bridge] resume` and one prompt holding
  the newest event of each subject, so ten events on one pull request read as one line. It does not resume the same
  session again for 120 s, until the new process shows in the sessions directory;
- leaves the events unacknowledged when the session did not take them, so the server redelivers them after its ack wait.

Before it notifies, the bridge drops the lane moves `[bridge] quiet_moves` names, by destination lane and writer (the
move's `actor`, or `self` for a move the receiving session wrote, its URL and local ids read as one), and acknowledges a
batch left empty without notifying or resuming anyone. The subjects stay published, so a consumer's newest-per-subject
start still reads the latest move. With no table every move is delivered. A deployment quiets the moves its holders take
no action on (a move it wrote itself, a merge's Done, a green PR's Review) and keeps the ones that take work from a
holder or hand it back, such as an operator's close or a red PR's return to the working lane.

A resumed process has a new socket and token: it registers again by running `starpulse subscribe` for any subject.

### The sweeper

`starpulse worker sweeper` (a `ctx-sweeper` thread of the `contexts` child under `serve`) is the one reconciler. It
passes once at start and every `[sweeper] interval_s` (default 3600 s). A pass runs each kind in order, then the
housekeeping steps, and writes one journal line (`sweeper: pass N: readers=0 ...`) naming each kind and its correction
count. The built-in `readers` kind wakes a log reader that has entries waiting and made no progress since the last pass,
and counts it. The event-log prune is a housekeeping step of the pass.

A project declares more kinds and housekeeping as commands, each printing its result on its last line, a count (`3`) or
`{"corrected": 3, "sampled": 8}`:

```toml
[sweeper]
interval_s = 3600

[[sweeper.kinds]]
name = "sessions"
command = ["bin/sweep-sessions"]
timeout_s = 120

[[sweeper.housekeeping]]
name = "tmp-purge"
command = ["bin/purge-tmp"]
```

One process holds the `sweeper` lease row of `starpulse_leases` (its pid). A second `starpulse worker sweeper` exits 1
naming the holder; a row whose pid is gone is taken over. `/metrics` carries `starpulse_sweeper_passes_total`,
`starpulse_sweeper_samples_total{kind}`, `starpulse_sweeper_corrections_total{kind}` and
`starpulse_sweeper_errors_total{kind}`. A kind or step that fails or times out counts an error and the pass goes on.

### What the page shows when the server restarts

The page keeps its last Board on screen while the connection is down and says why in the navigator's header, where the dot
and the `live · <time> MST` line sit. The note replaces that line until the connection is live again; `<time>` is the
clock time of the last data the page drew.

| State | Dot | Note | When |
| --- | --- | --- | --- |
| Live | green | `live · HH:MM MST` | The stream is open. |
| Restarting | amber, pulsing | `restarting · HH:MM MST` | The `health` subscription sent `restarting` before the server exited. |
| Stale | amber, pulsing | `stale · HH:MM MST` | The connection dropped and the page still shows the Board it drew, until the new read replaces it. |
| Retrying | amber, pulsing | `retrying · HH:MM MST` | The stream dropped with no announcement. |
| Offline | red | `offline · HH:MM MST` | The stream has been down for 20 s, from the drop or the announcement. It keeps retrying. |
| New build | green | `updating when idle` | The `health` subscription's `build` is a page build other than the one loaded. |

The dot does not pulse under `prefers-reduced-motion`.

The page reconnects at once after a drop, then waits 250 ms, 500 ms, 1 s, 2 s and 3 s between tries and keeps trying at 3 s.
Each connect replaces the page's Board with a fresh snapshot.

The page keeps nothing between loads: a load reads the Board over `POST /graphql` (`tasks`, `board`) and `POST /api/jobs`, then
follows it with the `taskChanges` and `jobChanges` subscriptions from the positions those reads answered, the merge Ledger's
`occurrenceChanges` marks and one `health` subscription ({components, build, restarting, at}) that drives the link dot, the
build check and the clock. A page holds what it drew through a drop, marked `stale`, until the next read replaces it; a server
still `reading` its board does not replace it. A position the server no longer holds answers `410` and is read again at once.

While the Board is replaying after a start, the feed publishes no delta, so a consumer such as the
scheduler never acts on a delta twice; the Board it reads then is the one the replay built. `FEED_EVENT_RESEND` in the feed
module is the table of kinds a restart resends: only `snapshot`.

The `health` subscription carries what the page needs besides the Board:

- `build`: the page build the server is serving, the first 12 hex digits of the SHA-256 of `static/index.html` (whose asset
  names carry each bundle's hash, so a rebuilt page has a new id). The first build a page's first connection names is the build
  it was loaded from; a later connection that names another makes the page show `updating when idle`, once the server is no
  longer `reading`: a page reloaded onto a server still reading its board would draw the partial Board it holds.
- `restarting`: set for every open subscription when the server receives `SIGTERM`, before it exits, after it has waited up to
  one second in all for the open streams to write the frame. The server then saves the Board and stops.

A page that holds a new build reloads itself once nobody is using it: no task view, dialog or menu open, no field focused,
and no pointer, key or wheel input for 30 s. A tab in the background reloads at once. It reloads once per build: the page
records the build it reloaded for in `sessionStorage` (`starpulse.reloadedFor`), so a build that still differs after the
reload does not reload it again.

## Endpoint reference

Every HTTP endpoint `starpulse serve` answers, with its payload and refusals. The schema is `starpulse/schemas/api.schema.json`; the OpenAPI 3.1 document of every route is `starpulse/schemas/openapi.json`, served at
`GET /api/openapi` and drawn at `GET /swagger` (Swagger UI from a pinned jsDelivr release, so the page needs internet); the implementation of a pull request row is `PullRequests._row`.

```text
Every write (POST /api/..., PUT /api/admin, PUT and DELETE /api/history-window) must be `Content-Type: application/json` (else 415) and carry
no `Origin` or this server's own (else 403), so a web page on another site cannot write through the operator's browser.
It listens on --host, 127.0.0.1 by default.

GET /              the page, built by `pnpm --filter @starpulse/web build` into static/: one view
                   that drills Board → Board state → machine, or Board → workflow. After its first
                   reads it asks for nothing but its `/graphql` subscriptions
GET /board, /flow/<name>, /runs
                   the same page; it opens the level that draws that graph, then rewrites the address to /
GET /api/snapshot  the Board as one response, for the CLI: without each task's description and criteria
                   (`/api/task/<id>`) and with only the day's settled tasks, each active task keeping its `moves`;
                   `?view=full` and `/api/flows` send this same stored body (gzip once per stored body), which
                   `starpulse snapshot` and `starpulse board|task|machines|machine|doctor|incident` read; a verb
                   that needs a task's description or criteria reads `/api/task/<id>`
POST /api/jobs     {position, items, domains, cues, pools, error}: every runs workflow as a job with its latest run and its runner's `startUrl` (empty when the instance sets none), the config's domains and cues, the concurrency pools (`<instance>/<pool>`), and what a runs instance reported; `starpulse runs list` reads it
GET /api/jobs/<name>  one job as the list holds it; 404 for a name no instance serves
POST /graphql      `subscription { health { components { name ready detail } build restarting at } }` sends the readiness components (the `GET /api/health` read, which stays for probes), the page build id, whether the server announced a restart, and the server's clock `at`, on connect and again whenever the components, the build or the restart change; the page's link state, idle reload and clock offset read it, and it reads the components again at least every 15 s, however busy the stream, and on each delta while one is unready, never per delta in between while all are ready
POST /graphql      `subscription { jobChanges(from: <position>) { jobs error domains cues pools } }` streams the full job list on each change after `position`; a `from` the server no longer holds answers 410, and the page reads the list again
GET /metrics       Prometheus text: `starpulse_page_build_info{build}`, 1 for the page build id the `build` event
                   names (none without a build); `starpulse_docs{type}`, the open board docs of each type; `starpulse_open_pulls{repo}`, the open pull requests the PR store holds in each repository; `starpulse_snapshot_build_seconds_count` and `_sum`, the snapshots the API built and the
                   seconds they took (0: it serves the stored one); `starpulse_board_lane_unattributed_total`, the board:lanes entries
                   any process appended since this one started that name no actor; `starpulse_machine_conformance_violations_total{machine}` and
                   `starpulse_machine_conformance_events_total{machine}`, the recorded moves of each machine that no
                   transition declares and all it judged. Also this process's `process_resident_memory_bytes`,
                   `process_threads`, `process_open_fds` and `process_start_time_seconds`, which moves on every
                   restart. With `[board.actor]`, also `starpulse_task_actor_refusals_total` and the
                   `starpulse_task_actor_latency_seconds`, `starpulse_task_actor_projection_seconds` and
                   `starpulse_task_actor_handoff_seconds`, `starpulse_task_merge_move_seconds`,
                   `starpulse_task_park_release_seconds` and `starpulse_task_receipt_done_seconds` histograms, and the gauges
                   `starpulse_task_actor_recovery_finished` and `starpulse_task_actor_merged_review_waiting`
GET /api/doctor    {ok, checks}: the `cue:` and `repo:` checks of `starpulse doctor` against this server's snapshot and config,
                   each {check, status (pass, warn, fail), reason}, held for a minute; the Ledger's banner reads it.
                   No checks (and ok) when the server runs with no config to check
GET /api/openapi   The OpenAPI 3.1 document of every route (`starpulse/schemas/openapi.json`)
GET /swagger       Swagger UI drawing that document (loads a pinned release from jsDelivr)
GET /api/health     {ready, components}: 200 when the event log opened at the schema head (one a deploy's migrate moved ahead since still counts), the Board is assembled and every
                   context this `serve` supervises has started, else 503 naming each component (`store`, `board`, `writer`,
                   `contexts`) that is not, each {ready, detail}; reads no task and writes nothing. `starpulse doctor` and
                   `starpulse rehearse` read it
POST /api/machines
                   {machines}: every machine the board draws, each `{name, type, parents}`; the body takes no field.
                   `type` is `machine`, `phase machine` or `sub-machine`, `parents` the machines whose submachines name it
POST /api/daily-reports
                   {items}: one machine's counts and summed durations of its moves, read from the stored daily rows
                   (`starpulse_daily_report`, one per machine, local day and transition, days cut at America/Phoenix
                   midnight) and never from an event table. The body is `{offset, limit, filter}`: `filter.machine`,
                   `filter.since` and `filter.until` (inclusive local dates) are required, `filter.state` keeps the
                   transitions out of that state, and `filter.bucket` sums the rows per `day`, `month`, `year` or the whole
                   `range` (the default); each item is `{bucket, count, seconds}`, `limit` (default 1000, at most 10000)
                   buckets from `offset`. A range with no move is an empty `items`; a missing field or `since` after `until`
                   is 422
GET /api/machines/{name}
                   One machine's declared config: `{name, type, parents, skill, submachines, launches}`. `skill` is the one
                   its first parent link runs it with (empty when none names one). The Board's carries `lanes` too: each
                   lane's `tools`, `exits` and `skill`, read from the policy on each request (empty with no policy). An
                   unknown name is 404
GET /api/done[?before=T][&limit=N][&milestone=M]
                   {tasks, more}: the next `limit` done tasks (default 20, at most 100) past their hot day,
                   newest done first, each {id, title, state, model, labels, milestone, type, follows, entered} read from the
                   board on request. `before` is the `entered` of the last one held (epoch seconds; none: the newest). `milestone`
                   keeps the tasks of that milestone, filtered in the read model, so `board --milestone` pages only that milestone.
                   A board that cannot read a task is 404, a bad `before` or `limit` 400
POST /graphql      a Task's history is four fields of the Task detail: `lanePath` [{at, from, to, by}], `machinePath(machine)`
                   {path [{at, event, state}], steps}, `planRevisions` and `events(since)` [{at, machine, event, from, to}].
                   An unknown `machine` is a GraphQL error, and an id the board does not
                   hold, a run id included, answers `task: null`. The machine events are copied from their stream as they
                   arrive into the history database (`database_url`, else starpulse-history.sqlite beside
                   the config), so the path outlives the stream's trim. A trim past entries the copy never read leaves it resuming at the oldest kept row
POST /graphql      the views a board shows come from the task query: each Task carries `phase`, `substate`, `skill` {name, states, current, next},
                   `interactive`, `criteria` [{text, checked}], `pauseReason`, `readable` and `released` {at, session, last_renewal, ttl, idle},
                   and `board` answers `columns`, `roles` (the state roles), `machines` (each machine's states, transitions, submachines and next edge),
                   `dags` and the runs `error`, as the stored body holds them
GET /api/harnesses  {tiers, harnesses} as the last PUT set them, else from the config's `harnesses_file`; both empty with no file
PUT /api/harnesses  {tiers} and/or {harnesses: [each harness that changes, whole, as GET answers it]}, kept in the history
                   store, which `POST /api/start` checks too; 400 for a body that leaves a harness without every tier,
                   404 with no `harnesses_file`. A client that reads `harnesses_file` itself sees no PUT
Connect `starpulse.v1.CloudEventsIngest` Publish and PublishBatch on this port (docs/sources.md)
                   post machine events and runs as CloudEvents 1.0, with `authorization: Bearer <token>` of a `[[producers]]`
                   entry; the one write path for both over a port, needing no Redis. A machine event is written to
                   `machine:events`; a `StepStarted` or `StepFinished` with no `machine`, `subject` the run's id and
                   `data` {workflow, status[, step, depends]}, to `runs:events`. 400 for an event the contract refuses,
                   401 for a missing or wrong token, 403 for another producer's source, machine or actor, 413 over the
                   limit, 503 when the log refuses it, 404 when no producer is declared. A batch is checked whole, so a
                   refused entry writes none; a 503 may leave the entries before it committed, and posting the batch again adds only the rest
POST /intake/temporal-completion?workflow=<type>  Temporal's close callback (`Nexus-Operation-State`, `Nexus-Link` headers) with the `[[producers]]` bearer of a producer
                   named `temporal`; writes the run's close to `runs:events`. 201 {accepted}; 400 for a missing state, link or workflow, 401 for a wrong token
POST /intake/grafana  a Grafana notice, with the `webhook_token_env` bearer; saved as one `alert-notice` event under `webhook_producer`, answered 202 with no command run, 503 when the log took nothing; 404 where none is configured
```

## Event store

`starpulse/event_log/store` keeps one append-only stream per subject, `(subject_kind, subject_id)`, in
`starpulse_stream_events` (migration 0027). A row is a typed envelope (`event_id`, `version`, `type`, `schema_version`,
`at`, `actor`, `writer`, `definition_hash`, `causation_id`, `correlation_id`) and a JSON `payload`.

- `EventStore.append(kind, id, expected_version, events)` is the one write path. It compares `expected_version` with the
  stream's head and raises `StaleVersion` on a mismatch; the unique `(kind, id, version)` constraint turns a racing
  writer's collision into the same error. The events of one append commit together or not at all.
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

`serve` reads no machine file at start or on a reload: the store is the source, and a machine changes only through
`PUT` and `DELETE /api/machines` (over the `hash` that `GET /api/machines/{name}` reports). The files are an optional
copy. `starpulse machines import [PATH ...]` (`starpulse/runtime/machine_files.py`) activates the Board's `[board]
machine` file and each file in `.starpulse/machines/` (or the `PATH`s named) as each machine's active version, the way a
first install fills an empty store, and makes an imported file the active version over one the store holds. A file the
registry refuses exits 3 with the reason and leaves the others as they were; a Board machine that strands live Tasks
(`StrandedTasks`) exits 4 after the other files are in, and the active Board version stays. `starpulse machines export
[--out DIR]` writes each active machine as `<name>.yaml` (default `.starpulse/machines/`), and an export imported into
a fresh store gives the same active set. `starpulse policy export [--out FILE]` and `starpulse policy import FILE` do
the same for the governing policy as one JSON document.

## Task read model

`starpulse/event_log/readmodel` folds the `task` streams into tables that answer reads by index, so no read loads every
Task. A `Projector(engine, store)` folds events past its checkpoint (`read-model:tasks`, in `Checkpoints`); each batch of 500
commits its rows and the checkpoint together. The read model and the stored snapshot are derived families on the table registry: each keeps a stamp
in `starpulse_settings` (`derived_stamp:<family>`), and writer start (`build()`, from `starpulse migrate`) folds the read model
again only when it differs, from the table definitions, the fold and placement code and the machines that place a task.
`rebuild()` folds the whole History in memory, then swaps the tables, rows, fold cursors and stamp in one transaction, so a
reader sees the old rows or the new, never none; a replay and an incremental fold give the same rows. Consumer cursors in
`starpulse_checkpoints` keep their place, and no checkpoint name carries a hash. Given a `SearchIndex` as `search`, the projector also writes each folded Task's search
row in that transaction, in lane `archived` when the row is archived and not Done (an archived Done Task keeps the `Done` lane); no non-test code constructs it yet, so `serve` does not.

- `starpulse_tasks` (migration 0029) has a typed column per StarPulse field, JSON `fields`, `meta` and `comments`, and
  `seq`, the position of the last event folded into the row; the projector skips an event at or before it, so a second
  reader folding from a stale checkpoint adds no Criterion twice. `starpulse_task_criteria` holds one row per Criterion.
- Partial indexes `WHERE archived = 0` (`ix_starpulse_tasks_live_{id,state,milestone,assignee}`) keep the live set small
  whatever the archive holds. `ix_starpulse_tasks_seq` serves the delta read.
- `ReadModel(engine, declared)` is the query surface: `task(id)`, `snapshot(done, since)` (the live set: unarchived Tasks
  outside the done lanes, or in one and changed at or after `since` (`LIVE_WINDOW_S`, 24 h before now); partial index
  `ix_starpulse_tasks_live_set` on `(archived, state, updated_at)`, migration 0043), `held_states()`, `with_field(name, value)`,
  `ready(state, done)` (live Tasks in `state` whose every dependency is in `done`; a dependency with no row blocks) and
  `since(seq, limit)` (the delta: rows changed after a cursor, archived included). Each statement is a SQLAlchemy `Select`
  in `readmodel.queries`; its test asserts the plan uses an index and has no table scan.
  `archived(before, limit)` pages the archive newest first (partial index `ix_starpulse_tasks_archived_updated`, migration 0031) and
  `position()` is the highest `seq`, the cursor a cache keys on.
- Only `readmodel` reads `readmodel.tables` (the `readmodel-table-private` import contract).

`BoardFeed(read_model=ReadModel(engine))` serves the page from it: the reader switch, with no bridge between the two
paths. The feed holds no Task: each `snapshot()` queries the live set, so a Task Done more than 24 h ago is off the
Board and read only by id; `task`, `held` and `is_done` are single-row reads, `is_resident` is always false,
`cold_page` pages `archived`, and the snapshot carries no archived Task. The Scheduler's
`open_tasks` and the write guards go through the same reads. `follow_read_model()` publishes the Tasks changed since it last
ran as page deltas, to run after each `Projector.catch_up`. Without a read model the in-memory path serves unchanged. `serve`
folds the History into the read tables on each commit to the store: `Projector.fold_tasks` on a `task-fold` thread of its own, so a new Task's row waits for no other fold, and on the `read-model-follow` thread `Projector.fold_machines`, then `follow_read_model`, then `Projector.index` for search, so the page never waits on the index, draws the board from them
so the board reader opens no task file. The read model is the only read path; a config that still sets the old `read_model` key is refused as unknown. Run `starpulse import-board` first. In this mode entered and workable-since times are approximated, and the overlays for runs,
pulls and acceptance criteria are empty on the board card; `/api/task/<id>` returns the full record, whose `createdBy` is the session that filed the task (`created_by` in its front matter, empty when none); an archived task is read from the archive too, its body `archived: true` and `entered`, when the read model last changed its row (a Done task's entry into Done); the record carries the stored pull requests it cites as `pulls`. `GET /api/task-records?ids=A,B` returns those records in one read as `{records: [...]}`, leaving out a task the board cannot read. A record costs about 3 ms, so a read of 8 ids holds p95 under the 50 ms budget in a local load run and 50 ids read about 180 ms; the agent CLI reads 8 at a time. The search index is its
own FTS table, queried by term and never by loading Tasks; `put` still feeds it, so the cutover feeds it from the read model.
`ci/test_read_model_latency.py` (nightly) serves 20,000 Tasks with 18,000 archived and holds every read surface to the page
budget and the board to its soft memory limit.

## Task History

The native board appends every Task write to the Task's `task` stream (`board/task_history.py`) first; no task file is written. A verb reads its base from the History and appends with a compare-and-set at the head it read; one wrapper around the board's `writer`, `assign`, `edit`, `archive`, `restore`,
`complete`, `retire` and `create` covers every entry path: the `starpulse task` verbs, `PUT /api/tasks`, `PUT /api/tasks/{id}`, the page, the
Scheduler and the task actor, which all call those verbs.

- The Events are the intent the History's replay and the verb's result show: `TaskCreated`, `FieldsEdited` (own columns and `meta`),
  `Transitioned` (both states), `CriterionAdded`, `CriterionChecked`, `CommentAdded`, `Claimed`/`Released`, `Archived` and
  `Rehydrated`. A refused write appends nothing.
- A plan rewrite on a started task also appends `PlanRevised` (`ordinal`, `reason`, counted per task from 1), after the
  `FieldsEdited` it accompanies. The `PUT /api/tasks/{id}` change `planReason` carries the reason; the edit is refused without it.
  The fold ignores the Event; a Task's `planRevisions` field reports the count.
- A Task with no History takes no write (`<task> has no History, so it takes no write`) and a create over an existing
  History is refused: `starpulse import-board` and `starpulse parity --import` give a file its `TaskImported`.
- An append that finds the head moved re-reads it and retries, up to five attempts in all; a failed or lost append fails
  the write and writes no file.
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
reads and writes that state through the `starpulse` CLI, the HTTP API or the native board ([adapters](adapters.md)),
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
the planner statistics stay fresh. The limit bounds the file after a checkpoint; it does not cap growth between them,
and SQLite restarts the log only when no reader is on it. The api worker therefore runs one thread that, every
5 s the `-wal` file is past the limit, runs a `TRUNCATE` checkpoint, which waits up to a second for the readers on old
frames, so readers that always overlap no longer keep the log from restarting. A connection checkin in any worker runs
no checkpoint and holds no writer off.

```toml
# Every top-level key and table is described in the settings reference below; a setting left out takes its default.
database_url = "sqlite:////var/lib/starpulse/history.sqlite"
event_log_retention_days = 7   # the default
event_log_archive_dir = "starpulse-archive"   # the default
# pull_requests = true
# take_over_command = ["/usr/local/bin/take-over"]
# webhook_producer = "grafana-alerts"
# webhook_token_env = "STARPULSE_WEBHOOK_TOKEN"

# [worker_memory.contexts]
# soft_mb = 1536   # the default
# hard_mb = 3072   # the default


# The board: `type` is `native`, the only board; a config cannot name an outside module.
# The rest of the table is that board's settings.
# With no [board] table the view draws its own Markdown board, `type = "native"`:
[board]
type = "native"
# path = ".starpulse/board"  # the board's directory, relative to this file; created empty when absent
# machine = "board.yaml"     # a machine file for the Board: its transitions and `writers` decide which moves are offered, and to whom; every other file in `.starpulse/machines/` is drawn as a flow. Every lane must be one of its states; a state that is not a lane must be `initial` or `final`, is drawn, and is never offered as a move (a creation or archive state), else `serve` refuses to start
# holds = "my-holds {id}"    # prints a JSON array of reasons the task actor withholds the task's `deps_done` (see Task actor)
# unfinished = "my-unfinished {id}"  # prints a JSON array of the work a task whose pull requests merged still has; the task actor routes it to Ready instead of closing it (see Task actor)
# parked = "my-parked {id}"  # runs after the task actor moves a task from the working lane to Waiting, to tell the session that holds it (see Task actor)
# released = "my-released {id}"  # runs after the task actor moves a task from Waiting to Ready, so a session parked mid-work is resumed whether or not anything admits Ready tasks (see Task actor)
# returned = "my-returned {id}"  # runs after the task actor moves a task into the working lane (a Review task whose pull request turned red, draft or conflicting, or a failed post-merge QA), so the session that delivered it is woken to fix it
# alive = "my-alive {id}"  # exits 0 while the session holding the task is alive; `pr_unfinished_alive` holds on it, `pr_unfinished_dead` on a nonzero exit
# enqueued = "my-enqueued {id}"  # runs when a same-lane route fires (an `ENQUEUE` that leaves the task where it is), such as queueing a green Review pull request for merge
# closed = "my-closed {id}"  # runs after the task actor moves a task to Done, so the board can file what follows the close (see Task actor)
# archived = "my-archived {id}"  # runs after the task actor archives a task, so the board can close the pull requests it leaves open (see Task actor)
# validate = "my_checks:task_write"  # may refuse a task write before it lands (see docs/adapters.md)
# transcripts = "~/.claude/projects"  # where Claude Code writes each session's transcript; the harness telemetry reads a session's last turn there, and a terminal halt (a synthetic error reply opening `Autocompact is thrashing`) ends the session with a `SESSION_ENDED` event; only the transcript's last 64 KiB is read
# types = ["spike", "bug"]  # the names a task's `type` may take; a write setting any other is refused with this list in its reason, so with no list any non-empty type is accepted and a board names none of its own
# complete_done = false     # true: a task landing in Done, and each Done task left in `tasks/` at start, is archived, which the reader and search still find
# complete_keep_labels = "" # a regex: a Done task with a label that fully matches it stays on the board, Done and writable, where `complete_done` would archive it

# Task fields this deployment adds to StarPulse's own, checked on write and kept in the read model (see Task read model):
# [board.fields]
# area = { type = "string", queried = true }  # type: string, integer, number or boolean; queried gives an indexed generated column, so a read filters by this field without a scan

# Rules every task write must satisfy, whoever makes it: the agent CLI, the page or a workflow (see Board guards in
# docs/public-surface.md for every primitive). Each is judged on the task as it will be after the write, by the actor
# that makes it, and the first one broken refuses the write with its `reason` (and `skill`), the same text to the CLI
# and the page; nothing is written. A board with no rules accepts every write it accepted before. A move by an actor
# the board's `warn_actors = ["operator"]` setting lists that breaks a lane rule (`to`, `from`) lands instead, and the
# answer's `warnings` lists the rule's reason; a write rule (`write = true`, `create`) still refuses that actor. The
# page reads the same rules beforehand from the task's `moves` in `POST /graphql`, as `warnings` (`reason`, `skill`) on that actor's
# verdict (the stream's snapshot leaves its moves unguarded), so the kanban asks the operator to confirm before it posts
# the move.
#   on       = { to = "Done" }                 a write that enters Done (`from = [...]` narrows it to those states)
#            | { to = "Done", while = true }   ... and a write that leaves the task in Done
#            | { write = true }                every write, whatever the task's state
#   require  = one primitive: field, label, section, body, block, dependencies, checklist, readable, retained, no_implied_dependency, pull_proof, matrix_profile, qa_verdict, pulls_ready, pulls_failing, pulls_clear, pulls_changed, archive_cited, or all_of, any_of, exactly_one,
#              none_of over a list of them
#   unless_actor = ["temporal/reconciler"]         actors the rule does not judge: operator, agent, <instance>/<workflow>
# [[board.guards]]
# on = { to = "Done" }
# require = { field = { field = "references", matches = "/pull/\\d+$", min = 1 } }
# reason = "Done needs a pull request in references"
# skill = "completing-tasks"
# unless_actor = ["temporal/reconciler"]

# Entry effects: what entering a lane does to a task, whoever moves it (the page, the agent CLI, the task actor, a
# create). Each fills a front matter field the task holds none of; the one value is `{ matrix = true }`, which
# reads `[board.default_profiles]` by the task's `kind-*` and `size-*` labels (`profile` only). It runs before the
# lane's guards judge the write, so a Ready guard that wants a profile finds the one the matrix gives.
# [[board.entry]]
# lane = "Ready"
# set = { profile = { matrix = true } }

# Optional: move a task on the facts its lane waits on (see Task actor). Its presence turns the
# actor on; optional `repo = "owner/name"` is the repository whose pull requests the board renders as a bare `PR #N`, and the board must edit tasks, else `serve` refuses to start. With it, the [release] polling pass does not run.
# [board.actor]

# [ci]
# states = ["in_progress", "review"]

[[runs]]
name = "temporal"
type = "temporal"
url = "http://temporal.example.com:8080"
start_url = "http://temporal.example.com:8080"   # where the page's Run in Temporal ↗ link opens
domains = { Data = ["nightly", "etl"] }  # how the page groups this instance's workflows

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
# adapter = "github_actions"  # optional: a run adapter type whose own status labels its Step events carry, read through its `status_of`

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

# Optional: what harness telemetry is read against (see Fold what each session did and Group recurring work in
# docs/sources.md). Every key is optional; with no table nothing is declared, and no path is an area.
# [analytics]
# roots = ["/srv/repo", "/srv/repo/.claude/worktrees/*"]  # absolute checkouts a path is cut to an area under; `*` is one component
# size_bands = { 1 = [50, 14], 5 = [170, 47] }          # each size -> [p90 steps, p90 active minutes]; no verb reads it now; a config that sets it still loads
# injected_openings = ["<task-notification"]               # a prompt opening with one is labelled `injected`, any other `human`
# [analytics.session_origins]                              # per origin name, the first-prompt prefixes that open a session it names
# "start service" = ["Start TASK-"]                        # a session whose first prompt matches none is `operator`; the row reports it as `origin`
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
# phases = ["starting-tasks", "completing-tasks"]            # lifecycle skills in order; a session's `role` is the furthest it loaded
# ladder = ["haiku-low", "haiku-high", "sonnet-high"]      # `<family>-<effort>` profiles, cheapest first; a move up is a raise
# default_repo = "owner/name"                              # no verb reads it now; a config that sets it still loads
# completion_call = '\.venv/bin/deliver\b'                 # a shell command run after that skill loaded

# Optional: rank search by meaning as well as by words (see `search` in docs/cli.md). `embeddings_url` is an
# OpenAI-compatible embeddings endpoint, local or cloud; with it unset, search is lexical and nothing calls out.
# [search]
# embeddings_url = "http://localhost:8080/v1/embeddings"  # optional: POSTed `{model, input}`, answered with `data[].embedding`
# model = "nomic-embed-text"                             # required with embeddings_url: the model the endpoint is asked for
# token_env = "EMBEDDINGS_TOKEN"                         # optional: the environment variable holding the endpoint's bearer token
# rerank_url = "http://localhost:8005/v1/rerank"         # optional: reranks the duplicate search's nearest tasks (no token is sent)
# rerank_model = "Qwen/Qwen3-Reranker-0.6B"              # required with rerank_url
# rerank_query = "<Query>: {query}"                      # optional: the instruct template for the query, with its {query} placeholder
# rerank_document = "<Document>: {document}"             # optional: the template for each candidate, with its {document} placeholder

# Optional: map the steps a shipped skill names to this project's own command lines (see `command run` in docs/cli.md).
# Each name maps to an argv, run with no shell. Placeholders: {task}, {worktree}, {NAME} (from --arg NAME=VALUE), and the
# whole element {args} (the arguments after `--`); write a literal brace as `{{` or `}}`. `starpulse config check` refuses a malformed entry.
# [project.commands]
# deliver = ["./bin/ship", "{task}"]
# test = ["make", "test", "{args}"]

# Optional: have `serve` run the Claude Code receiver (see docs/sources.md); every key is optional.
# [claude_code]
# host = "0.0.0.0"         # the address to bind (default 127.0.0.1)
# port = 4321              # the port to bind (default 4318)
# redactor = "pkg.mod:redact"  # the filter a shell command's text passes through before it is stored; none keeps no command text

# Optional: have `serve` run the GitHub intake listener (see docs/sources.md); the secret and one of organisation or repositories are required.
# [github]
# secret_env = "GITHUB_WEBHOOK_SECRET"   # the environment variable that holds the App's webhook secret
# organisation = "acme"                  # accept every repository this owner has
# repositories = ["solo/tool"]           # accept these owner/name repositories as well
# inbox_files = "/old/inbox/*.sqlite"   # a glob for the old inbox database files `starpulse migrate` copies into the store once (unset: none)
# max_body_bytes = 5242880               # a larger body is answered 413 (default 5 MiB)
# host = "127.0.0.1"                     # the address to bind (default 127.0.0.1)
# port = 8767                            # the port to bind (default 8767)
# reconcile_token_env = "GITHUB_APP_TOKEN"  # the environment variable that holds the token the sweeper's github kind reads GitHub with (unset: no kind)
```

### Runs adapters

A `[[runs]]` instance's `type` names one of the built-in adapters `github_actions`, `systemd`, `temporal` and `woodpecker`, or an installed
package's module. `serve` starts the worker of each built-in adapter that a configured instance names, as its own child
(`starpulse worker github-actions --config <this file>`, likewise `systemd` and `woodpecker`; `temporal` has none, its closes arrive at `/intake/temporal-completion`), and restarts it if it stops, as
it does its other workers. No OS service unit is needed for an adapter. With its worker down or not yet started, the
page shows the instance with the error "the woodpecker worker has not reported" or "last reported Ns ago" (its beat is older
than 60s).


### Settings reference

The board, `[scheduler]`, `[analytics]`, `[search]`, `[project]`, `[claude_code]` and `[github]` are described by the examples above and
by [Scheduler](#scheduler); `[level]` by the flow graph it draws. Every other setting is described below, generated from the
models in `starpulse/runtime/config_model.py`, which the loader takes its keys and defaults from: edit a description there, run
`python -m starpulse.runtime.config_reference`, and commit the result. CI fails when this section differs from the models.

<!-- config-reference:begin (generated by `python -m starpulse.runtime.config_reference`; edit the Field descriptions in starpulse/runtime/config_model.py) -->

#### Top level

- `database_url` (text): The SQLAlchemy URL of the history store; unset, `starpulse-history.sqlite` beside the config. The credentials never live here; they come from the driver's environment, such as `PGPASSWORD`.
- `event_log_retention_days` (whole number, 1 or more, default `7`): How long `serve` keeps the event log's rows: the sweeper prunes older ones at start and each pass, so the table, a SQLite file and every reader's replay at boot stay bounded. A reader that was down longer than this resumes at the oldest kept row. The `machine:events` stream is exempt: the prune never deletes it, because a read-model rebuild refolds every machine's tasks from it. On its first pass the sweeper also puts the archived rows of that stream back at their archived `id`, once. A whole number of days.
- `event_log_archive_dir` (text, default `"starpulse-archive"`): Where the sweeper writes each row it prunes, before it deletes the row (see Event log archive): a directory, relative to this file unless absolute.
- `worker_memory` (table of `[worker_memory.<context>]` table): The memory limits (proportional size on Linux, resident size on macOS) `serve` holds its two worker children to, in megabytes (see Worker processes), set as `[worker_memory.api]` and `[worker_memory.contexts]` with either key left out. Past `soft_mb` it replaces the child, past `hard_mb` it kills and restarts it. Defaults, soft/hard: `api` 4096/8192, `contexts` 1536/3072, `pulls` 1024/2048.
- `mode` (`"ic"`, default `"ic"`): `ic`, the one value: one person on one machine.
- `host` (text, default `"127.0.0.1"`): The address `serve` and `worker api` listen on; the default answers this machine only, and `0.0.0.0` answers the network. The `--host` flag overrides it.
- `port` (whole number, 1 or more, default `8766`): The port `serve` listens on. The `--port` flag overrides it.
- `hours` (number, above 0, default `6.0`): How far back a task's latest move on a machine counts; Admin's override replaces it. The `--hours` flag overrides it.
- `tls_cert` (text): The TLS certificate, relative to this file's directory; set with `tls_key`, else both unset.
- `tls_key` (text): The TLS private key, relative to this file's directory; set with `tls_cert`.
- `session_start_url` (text): The session-start service a started task is sent to (`POST <url>/start/TASK-N?harness=&mode=`); unset: nothing can be started.
- `harness` (text, default `"claude"`): The harness adapter a session runs in: its session records, transcripts and inbox sockets are read through it. `claude` is the only one that ships.
- `harnesses_file` (text): A file, relative to this one, that declares the tiers and per-harness models.
- `pull_requests` (true or false, default `true`): `serve` keeps a pull request store, current from the lifecycle events and GitHub's webhook deliveries, that the task detail's `prs`, the `pull` query, the `ci` trail and `[release]` read. false never updates it: no event is applied, tasks carry no PR state, and those answer only from rows the database already holds. Set it on a second instance beside one that reads the same repositories, so one store is kept.
- `webhook_producer` (text): The `[[producers]]` name `POST /intake/grafana` saves each notice under, once the bearer token `webhook_token_env` names matches: one `NOTICE_RECEIVED` event of the `alert-notice` machine, answered 202 with no command run. 503 when the log took nothing, so the sender retries. 404 when this is unset. Needs `webhook_token_env` and the producer's `alert-notice` machine.
- `webhook_token_env` (text): The environment variable holding the bearer token `POST /intake/grafana` requires; the value is the name, never the token.
- `github_token_env` (text): The name of an environment variable holding a GitHub token. `serve` exports its value as `GITHUB_TOKEN` and `GH_TOKEN` before it starts any worker, so the GitHub reads and the child processes sign in with it; unset, or naming an unset variable, leaves both as they were. The value is the name, never the token.
- `take_over_command` (list of text): The command `PUT /api/tasks/{id}` with `interactive: true` runs, as an argv: StarPulse appends the task id and the command asks the task's workflow engine to flip that task's workflow to interactive, so it types nothing more into the task's session. Exit 0: sent (200). Exit 1: the task has no running workflow (409). Any other exit: an error, with the command's stderr. 404 when this is unset. The command is the only place a workflow engine appears.
- `runs` (list of `[[runs]]` table): One instance of a runs adapter per `[[runs]]` table.
- `producers` (list of `[[producers]]` table): A system that posts machine events as CloudEvents (see docs/sources.md, Post machine events as CloudEvents). The Connect `starpulse.v1.CloudEventsIngest` answers 404 until one is declared. A producer writes only the machines and actors listed here.
- `views` (list of `[[views]]` table): One view per `[[views]]` table: the GraphQL document its page runs at `/graphql`.
- `repos` (list of `[[repos]]` table): A repository whose merges apply through the parent's pin bump rather than a run of their own.
- `ci` (`[ci]` table): Draws each task's pull-request CI as a sub-flow of these Board states.
- `release` (`[release]` table): Releases Waiting tasks natively. With the table present, `serve` moves a Waiting task to Ready once every task it depends on is Done (see Release); with no `[release]` table it releases none. The board must edit tasks and draw `waiting` and `ready` lanes, else `serve` refuses to start.
- `board` (table): The board: `type` is `native` (the only board, no outside module), and the rest of the table is that board's settings, shown in the Board examples above. With no `[board]` table the view draws its own Markdown board, `type = "native"`.
- `level` (table): The flow graph drawn above the Board (`starpulse.flow_metrics.model.level`).
- `scheduler` (table): The scheduler's policy; every key is optional (see Scheduler).
- `analytics` (table): What harness telemetry is read against (see docs/sources.md).
- `search` (table): Ranks search by meaning as well as by words (see `search` in docs/cli.md).
- `project` (table): The project's own command line for each step a shipped skill names.
- `sequences` (table of list of text): The phases a task goes through, in order, keyed by task type (`story`, `bug`), with `default` for a type it does not name. A lifecycle machine link that lists `routes` sends a task to the route its sequence names next.
- `awaits` (list of text): The lifecycle machines whose unfinished placement of a task ends in an event, so a session that settles meanwhile is not resumed: a link's lens in the phase it runs, or a machine with no link until it ends.
- `account_room_alert` (text): The name of the alert that fires while no account has room to start a session. The scheduler starts nothing while that alert's latest event is `firing` and wakes on `resolved`; unset, it never waits for room.
- `claude_code` (table): Runs the Claude Code OTLP adapter in the `contexts` child, listening on `host`:`port` (see docs/sources.md).
- `github` (table): Runs the GitHub intake listener in the `contexts` child: it saves each signed webhook delivery to the `github_inbox` table before it answers (see docs/sources.md).
- `bridge` (`[bridge]` table): The NATS bridge's server that `serve` supervises unless `enabled = false` (see The NATS server).
- `sweeper` (table): Sets the sweeper's pass `interval_s` (default 3600) and declares its kinds (`[[sweeper.kinds]]`) and housekeeping (`[[sweeper.housekeeping]]`) as commands, each with a `name`, a `command` argv and an optional `timeout_s`; a kind prints its correction count (see docs/serving.md).

#### IncidentReachFile

- `kinds` (list of text): Reach a held task with any of these `kind-*` labels (`execute`).
- `areas` (list of text): Reach a held task with any of these `area-*` labels (`starpulse`).

#### SubscriptionRulesFile

- `claim` (list of text): Subjects a session subscribes to when it claims a task of this kind, relative to the board and with the task as `{task}`: `task.{task}.>`.
- `pr_opened` (list of text): Subjects the session holding the task adds when a pull request of the task opens, with `{task}` and the number `{pr}`: `pr.{pr}.>`.

#### [bridge]

- `enabled` (true or false, default `true`): `serve` supervises a `nats-server` (the official release, checked against its pinned checksum) on `127.0.0.1` with JetStream on, as its `nats` child; false: none starts. A change restarts `serve`.
- `port` (whole number, 1 or more, default `4222`): The port the server listens on, on localhost only.
- `store_dir` (text): Where JetStream keeps its streams. Default: `starpulse-nats` beside the config.
- `sessions_dir` (text): Where `starpulse subscribe` and `starpulse register` record each session's inbox socket and token, and where `serve` reads them. Default: `starpulse-sessions` beside the config, which a CLI run from another checkout than the served one does not share; name a state path when they differ.
- `board` (text, default `"trantor"`): The `<board>` token of the subjects the bridge publishes, `starpulse.<board>.<entity>.<id>.<event>`.
- `subscriptions` (table of `SubscriptionRulesFile` table): The subjects a session subscribes to, by the `kind-*` label of the task it holds, `[bridge.subscriptions.<kind>]`. A kind with no table subscribes to nothing; a session leaving the task drops the task's subjects.
- `incidents` (table of `IncidentReachFile` table): The sessions `starpulse incident open <type> <key>` makes wait on its owner task, by incident type, `[bridge.incidents.<type>]`. Each table declares at least one of `kinds` and `areas`, and a task must match every one declared; a type with no table reaches none.
- `quiet_moves` (table of list of text): The lane moves a session's consumer acks without notifying the session, by destination lane: `review = ["starpulse/task-actor"]` quiets the task actor's moves into Review. Each value names writers as the move's `actor` records them, or `self` for a move the receiving session wrote itself. A lane with no entry notifies every move, and the published subjects are unchanged.
- `resume` (list of text): The command that resumes a session that has ended when an event on its subjects arrives, ending in the flag that takes the session id; the id and the events follow it as arguments. `{session}` and `{cwd}` in an element are replaced by the session's id and working directory, and the command runs in that directory.
- `end` (list of text): The command the task actor runs when a task enters a lane `end_lanes` names, and again each time the task's holder settles or ends while the task still sits in one; `{task}` in an element is replaced by the task id. It ends the task's idle session, so it should return at once rather than wait on the end. Empty runs none.
- `end_lanes` (list of text): The lane ids a task's entry runs `end` for, such as `done` or `archived`. Empty runs none.

#### [ci]

- `states` (list of text, required): The Board state ids the shipped `ci` machine is attached to as a sub-flow; one the Board lacks is refused. StarPulse ships one `ci` machine, which GitHub moves and StarPulse only observes (its `source` is GitHub). With `gh` available, each task with a PR is one agent in that flow, and its trail is the PR's pushes, check results, re-runs, conflicts, rebases, merge and close, read from GitHub every minute and kept in the event log (`machine:events`).

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
- `type` (text, required): The runs adapter: a module under `starpulse` or the dotted path of one an installed package provides. It offers `follow(url, runs, log)`, and optionally `declared_params(url, workflow)`, the parameter names a workflow declares, which `doctor` reads. See Runs adapters for what a built-in adapter reads and serves.
- `url` (text, required): What the adapter reads. A built-in adapter is an opt-in worker: `serve`'s `contexts` child runs it as a thread, or you run `starpulse worker <adapter> --config <this file>`, and, with it down or not yet started, the page shows this instance with the error "the <adapter> worker has not reported" or "last reported Ns ago" (its beat is older than 60s).
- `domains` (table of list of text or table of list of text): How the page groups this instance's workflows: each domain is a list of workflow names, or a table of process name to workflow list.
- `start_url` (text): Where this instance's runner starts a run; the jobs page's Run in <runner> link opens it.
- `commit` (`[runs.commit]` table): The run parameters that carry what a run applies, so the Ledger pairs a run with its merge for certain. Each key names a parameter; a key left out is a parameter this instance has none of.

#### [[views]]

- `name` (text, required): The view's name, which `GET /api/views/<name>` reads its document by; unique.
- `query` (text, required): The one GraphQL document the view runs at `/graphql`: a fragment of the fields its card reads and a named query for the first load. Config load parses it and validates it against the task schema (`schemas/tasks.graphql`); the operation names label `/graphql`'s request metrics.

#### [worker_memory.<context>]

- `soft_mb` (whole number, 1 or more): Past this the child is replaced: the old one stops, then a new one starts (the Page API starts its replacement first).
- `hard_mb` (whole number, 1 or more): Past this the child is killed and restarted. Above `soft_mb`.

<!-- config-reference:end -->

## Tracing

The Page API exports a span for each request to a read or write route, but not for a stream, which stays open too long
to be one span. Nothing is exported until the standard OpenTelemetry environment names an endpoint:
`OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`) turns it on over OTLP/HTTP, and
`OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` and the other `OTEL_*` variables apply as the SDK reads them. The config
file has no tracing setting.

A span is named `<method> <route>` (`GET /api/task/{id}`) and runs from the request's arrival to the last byte sent.
Its attributes are `http.request.method`, `http.route`, `http.response.status_code`, `starpulse.workers_busy` and
`starpulse.streams_open` (the request workers in use, the request itself included, and the streams open when it
arrived), and `starpulse.caught_up_s` when the request waited for the workers' writes.

Its children are `queue` (the wait for a handler thread), `compute` (the answer built) and `write` (the answer sent),
an `embed` for a search's vector, and a `sql` for each statement the request ran, with the statement's first 500
characters as `db.statement`. A slow read is a TraceQL query, such as `{ span.http.route = "/api/search" && duration > 1s }`.

## Scheduler

The scheduler is a switch, a capacity reading, an admission rule and a loop that acts on the rule. The switch is persisted in
the `scheduler.enabled` row of the history store's `starpulse_settings` table, so it survives a restart, and it starts off. A missing row,
an unreadable store or a malformed value reads as off. `[scheduler] state_dir` (relative to the config file) is where `starpulse migrate` looks for the older
state files. The toggle file of that older name (`TOGGLE_FILE` in `scheduler/model/toggle.py`) beside the config or in `state_dir` is imported once by `starpulse migrate`, keeping its modification
time as the row's `updated_at` (a row the store already holds wins), then renamed to the same name plus `.imported`.

`GET /api/admin` answers any address:

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
  "sessionsByHarness": {"claude": {"use": 1.0, "limit": 3.0}, "other": {"use": 0.0, "limit": 2.0}},
  "needsOperator": [{"task": "TASK-3", "title": "Choose the store"}],
  "blockedBy": [{"name": "cpu", "use": 95.0, "limit": 80.0}, {"name": "start-limit", "use": 48, "limit": 48, "count": 3}],
  "gateHistory": [{"at": 1788307200.5, "dimensions": [{"name": "cpu", "use": 95.0, "limit": 80.0}], "blockedBy": [{"name": "cpu", "use": 95.0, "limit": 80.0}]}],
  "display": {"scale": 100, "motion": true, "view": "constellation", "density": "comfortable", "clock": "24"},
  "theme": {"pack": "starpulse", "bg": "slate", "packs": [], "bgs": []}
}
```

`display` and `theme` are the choices every device draws the page in, held in the `admin.display` row of the
history store's settings, so they survive a restart and a new browser starts on them. A row never written reads as the defaults above.
`display` holds `scale` (font size in percent, 85 to 150 in steps of 5), `motion`, `view` (what a bare address opens:
`constellation` or `kanban`), `density` (`comfortable` or `compact`) and `clock` (`24` or `12`). `theme` holds `pack` and `bg`, the ids
of the chosen color pack and background (built in, or one in `packs` or `bgs`), and the imported `packs` and `bgs`. A `PUT` with
`{"display": {"clock": "12"}}` changes only the fields it names; a `theme` in a `PUT` replaces the whole theme. An unknown value is a 400
and changes nothing. `/api/scheduler` is gone: it answers 404.

`harness` is the harness the loop starts sessions on (default `claude`); `PUT /api/admin` with `{"harness": "<name>"}` selects another.
`quietHours` is the daily window in which the loop admits nothing, or `null` for none (see Quiet hours below).
`dimensions` lists `cpu`, `memory`, `sessions` and `review` in that order, each as its use against its limit; the
`sessions` meter follows the selected harness's cap: an Admin override if one is saved (see Session cap below), else
`[scheduler.session_limits]`, else `limits.sessions`.
`sessionCap` names that cap as `{"harness", "limit", "source", "configLimit"}`: `source` is `admin` for an override or
`starpulse.toml`, and `configLimit` is what the config sets.
`capacityLimits` names the `cpu` and `memory` limits the same way, each as `{"limit", "source", "configLimit"}`: `source` is
`admin` for an override (see Capacity limits below) or `starpulse.toml`, and the `cpu` and `memory` dimensions follow `limit`.
`sessionsByHarness` names every harness's in-flight count against its own cap. A started session counts while its task
is In Progress or it has shown an event inside half an hour of its start; one at a prompt that never claimed its task
frees its slot. A credit or usage pause for one
harness lands in `pauses` and blocks admission for that harness only.
`sampledAt` is epoch seconds, and `dimensions` is empty with `sampledAt` null until the first sample.

- `cpu` and `memory` are the host's busy share over the last 60 seconds and its used share, in percent, read with psutil. With a dispatch loop each is the use `blockedBy` judges, the sampled value plus the demand of a start the sampler does not count yet.
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
- `blockedBy` lists every gate holding admission back now, each as `{name, use, limit}` for `cpu`, `memory`, `sessions` or
  `review`, in that order (`next.reason` still names the first). While the start service refuses a start with "N of M task
  sessions are live" it adds `{name: "start-limit", use: N, limit: M, count}`, where `count` is the refusals since the
  last accepted start. It is `[]` when nothing holds.
- `gateHistory` is the last 20 gate readings (`at`, `dimensions`, `blockedBy`) the loop kept in its event log, newest
  last. A row is added when the blocking gates change, or five minutes after the last row; the log keeps 100.
  It is the loop's own record and needs no Prometheus.

`PUT /api/admin` with `{"enabled": true}` or `{"enabled": false}` sets the switch, and with
`{"quietHours": {"start": "HH:MM", "end": "HH:MM", "timezone": "<IANA zone>"}}` or `{"quietHours": null}` sets or clears
the quiet hours; `{"sessionCap": <whole number above zero>}` or `{"sessionCap": null}` sets or clears the selected
harness's session cap; `{"cpuLimit": <percent above 0, up to 100>}` or `{"memoryLimit": <percent>}` sets, and `null` clears, that
admission limit; a body may carry several. It answers the same body as the `GET`, and a body with anything wrong is a 400
that changes nothing. It answers only loopback and private-network (RFC 1918) addresses, with 403 elsewhere, and like every write it needs
`Content-Type: application/json`. A `serve` that runs no scheduler, an adapter-kit server, answers 404.

The sampler reads every 60 seconds. The first sample is a baseline; after it, a dimension going from below its limit
to at or over it, or back, logs one `StarPulse scheduler: <dimension> is full|free (<use> of <limit>)` line.

StarPulse Admin's Scheduler card shows it: the switch with **On** or **Paused**, a meter per dimension (amber from
80% of its limit, red past it, dimmed while the switch is off), the next pick as text (its task, title and `starting`
in green or `waits: <reason>` in yellow, or **Nothing eligible**), the count of sessions in flight (the Sessions
dimension's use, or the length of `inFlight` without it), the session cap row, the CPU and memory limit rows, and the quiet hours row. A click on the switch sends the
`PUT` with no dialog, and a refusal shows its reason under the switch. The card reads `next` from the same body when it
carries it, and shows no pick without it. It reads once when Admin opens and follows the `schedulerChanges`
subscription after. A server with no scheduler (404) shows the card with its reason and no controls. The Kanban draws no
scheduler control.

### Session cap

The Scheduler card's **Session cap** row sets the selected harness's cap from StarPulse Admin, over `starpulse.toml`.
`PUT /api/admin {"sessionCap": 12}` keeps 12 for that harness in the history store (setting
`scheduler.session_caps`, one value per harness); `{"sessionCap": null}` clears it, and the config's cap applies again.
Anything but a whole number above zero is a 400 that changes the stored cap not at all. The admission loop reads the
override on every pass and a save wakes it, so a new cap takes effect with no restart; sessions already running past a
lowered cap continue and the admission loop starts nothing new until the count falls under it. The cap bounds only
autopilot admissions: an ad hoc start (`POST /api/start`) goes through past it. The override survives a restart. The
sampler's full/free log lines still read the configured limit.

### Capacity limits

The Scheduler card's **CPU limit** and **Memory limit** rows set the two host limits from StarPulse Admin, over
`[scheduler.limits]` in `starpulse.toml`. `PUT /api/admin {"cpuLimit": 95, "memoryLimit": 70}` keeps both in the
history store (setting `scheduler.capacity_limits`, one percent per dimension); `null` clears one, and the config's limit
applies again. Anything but a number above 0 and up to 100 is a 400 that changes neither stored limit. The sampler reads
the limit on every call and a save wakes the loop, so the next admission pass judges cpu and memory against the new limit
with no restart, and the sampler's full/free lines follow it. The override survives a restart and a reload; the
`review` limit and the other settings have no override.

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
a pure function of the open tasks, the sampler's readings, the `[scheduler]` policy and the run ledger.

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
  then the other bugs (type `bug`, or labelled `board-state` or `regression`), then the tasks labelled `throughput`, then those labelled `leverage`, then the rest, then the `kind-decide` tasks. Within a class they go by
  the most open tasks waiting on them directly, then the deepest critical path (the task itself plus the longest chain
  of open tasks waiting on it), then the heaviest Priority weight, the lowest id breaking a tie. The weight is the `[scheduler.priority_matrix]`
  cell of the task's `<impact>/<urgency>` (`high/low`), 1 to 9 by default as the product of the two levels' places
  (low 1, medium 2, high 3); a task missing either field ranks under `default`, 4.
- **Log.** Each decision logs one line:
  `StarPulse scheduler: <task> admitted|refused (<dimension> full|no agent profile) enforced_rank=<n>`.
  The rank numbers the admitted tasks from 1; a refused task has none.

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
  The loop reads that event from the feed it already subscribes to once per sample.

Each pass starts the first admitted task, then decides again over readings that carry that task's demand, so two tasks that
do not fit together are never both started in one pass. A run holds its capacity from its start until its task leaves
`in_progress`; until the harness reports the session active the loop adds that demand to the sampler's readings itself.
A start that fails (`StartFailedError`) is logged and its task skipped for a backoff of 30 seconds that doubles with
each further failure, up to 30 minutes, unless the refusal names a usage or credit limit: admission for that harness then
pauses until the reset clock the message names (or five hours when it names none), `GET /api/admin` lists it under
`pauses`, and the next pick `waits` with `reason` `<harness> usage limit`. A refusal that names a missing binary
(`the starpulse binary is missing: <path>`, `needs <binary> on PATH`) fails again until the host changes, so it halts
admission for that harness for an hour after the first occurrence: one `ERROR` journal line names the refusal and path, `pauses`
lists it with `reason` `start halted: <refusal>`, and one start tries again when the hour ends. A start that succeeds comments
`Scheduler started <task>: <session address>` on the task; a board that refuses the comment leaves the session started.
A start the board or the session-start service did not answer (`did not answer`) leaves its task Ready for the next admission; any other failed start is handed to the task actor, which parks the task in Waiting on the task owning the fault through the board's `faulted` command, else in Needs attention with the reason.

A session starts through `session_start_url` when the config sets it; the loop's request is
`POST <url>/start/<task>?harness=<selected harness>&mode=interactive&by=scheduler`, so the service can brief an unattended session
unlike one an operator opened (an operator's start has no `by`, and the page's `POST /api/start` body names `harness` with
`mode` defaulting to `interactive`). With none, the built-in starter runs
`tmux new-session -d -s starpulse-<task> -c <config directory> claude --remote-control <task> "Start <task>"` and needs
`tmux` and `claude` on `PATH`, so a board with no `[scheduler]` table and no `session_start_url` starts a task out of the
box. The built-in starter starts only Claude: with another harness selected it refuses the start, naming
`session_start_url`, and ignores `mode`. The built-in starter is tmux only and has no multiplexer setting: a board whose sessions run in another
multiplexer (herdr) sets `session_start_url` to a service that starts them there.

When a run's task leaves the eligible lane and `in_progress`, the loop writes its outcome (the lane it went to), duration and
peak to the ledger. When the harness session stops while the task is still in those lanes, the run is written as
`session-ended` and the task is held out of admission until a person or the sweep moves it; a later tool or start on the
same session revives that run instead of starting another.
The scheduler never moves a task for an idle session. The sampler period (60 seconds) is the only timer; it finishes
runs and never admits.

The runs in flight, each task's last start time and the last capacity sample live in `starpulse_worker_state`
(`scheduler.inflight`, `scheduler.starts`, `scheduler.sample`), so a restart restores them: `GET /api/admin` still
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
dependents stay Waiting. A task whose description declares Start Criteria that name event subjects is left to those events, whatever its dependencies.

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
containment reads are the memoized GitHub REST calls the pull request projection makes; a path a merge does not pin (GitHub's
404) is a remembered answer too, so only a read GitHub could not answer is asked again.

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
editor as actor `starpulse/task-actor`. The board must edit tasks, else `serve` refuses to start. The table's keys are `repo`, `owner_source` and `gitmodules`. `repo` (`owner/name`) names the board's own repository: its pull
requests read as `PR #N` in a closing comment, every other repository's as its URL. `owner_source` is the `source` prefix of the tasks that own a shared check failure; with it and `repo` set, the `owner_stale` fact (below) reads that repository's `main`. `gitmodules` (a path from beside the config) names the parent's `.gitmodules`: with `repo` set, the actor answers the unfinished work of a task citing pull requests itself, the repositories its Modified Files name (a file under a submodule's path belongs to that submodule, any other to `repo`) with no merged pull request in the store, so a merge spawns no `[board] unfinished` command; that command answers only a task citing none. An actor with no `gitmodules` or no `repo` asks it of every task, and it checks only task branches.

The actor reads the `waits` of the Board machine and the transition each wait's event draws, so it moves only along a
move the machine declares. For a task in a state with `waits`, the first fact that holds fires its event:

- `pr_terminal`: every pull request the task cites is merged or closed in the PR store. A merged one is written with its
  merge commit as the proof in the edit's comment. A record that says merged with no merge time (an event's word, not
  a read of GitHub) is not terminal until the store's next read settles it.
- `pr_merged`: `pr_terminal` holds and at least one cited pull request merged, so a task whose every pull request
  closed unmerged stays. A state that parks work for a person may declare `waits: {pr_merged: MERGED}` to close a task
  whose delivery merged while it waited there.
- `pr_closed_unmerged`: `pr_terminal` holds and no cited pull request merged. A state that waits on it moves the task
  to Needs attention, asking whether to redeliver or archive it.
  A task whose comments show an `Operator answer` after the last comment carrying an ask's question is not parked on it
  again (`overdue`, `pr_failing`, `pr_closed_unmerged`); a different question parks it.
- `pr_closed_unmerged_complete`: `pr_closed_unmerged` holds, every acceptance criterion and Definition of Done item is
  checked, and a task comment opens `No merge needed:` (the work landed elsewhere or needed no merge), so a no-op task
  has nothing to ask. At the task's session settle an `Operator answer` after the last ask is that statement too: a
  session that ended its turn on the answer redelivered nothing. A checked task with neither is a rejected change and keeps the `pr_closed_unmerged` ask. A
  state that waits on it may declare an event that closes the task.
- `pr_merged_unfinished`: `pr_merged` holds and the board's `unfinished` command prints a non-empty JSON array of the
  work the merge leaves, so a task whose planned pull request in another repo never opened does not close. The edit's
  comment names the merge proof and the work left. A state lists it before `pr_merged` and maps it to a move into
  Ready. With no `unfinished` command, or an empty array, it never holds. A command that fails or prints no array
  holds it, with the error as the work left: a task is not closed on a board that cannot say what is unfinished.
- `pr_ready`: the task cites a pull request and any cited one is merged (with a merge time) or open and not a draft.
  The edit's comment names the ready and merged pull requests as the evidence. In the working lane a pull request
  merged before the task's latest entry to that lane (a post-merge send back) is the shipped work and does not hold
  the fact. A state may declare `waits: {pr_ready: REVIEW}` to move its tasks to Review once a pull request is ready.
  A Review state may map it to a route whose target is Review itself: the task stays and the board's `enqueued` command runs once per distinct evidence.
  A task moved from `review` to its working lane holds, for each pull request it cites, the head it was moved on: an open
  pull request still on that head is the reviewed work, so the fact does not hold for it until a push changes the head
  or the lane changes (the actor remembers it in memory only, so a restart clears it).
- `pr_failing`: any pull request the task cites as its own delivery is open with a failing required-check rollup
  (`checks` is `failing`). The comment names the pull requests, then `Blocker:`, `Options:` and a question, and is also the
  task's `## Needs attention` reason. A state may declare `waits: {pr_failing: DEMOTE}`.
- `pr_draft`: any pull request the task cites as its own delivery is open and a draft. A state may declare
  `waits: {pr_draft: SEND_BACK}` to return its tasks to the working lane, which runs the board's `returned` command.
- `pr_conflicting`: any pull request the task cites as its own delivery is open and conflicts with its base. The same
  `SEND_BACK` move serves it.
- `deps_done`: the task has dependencies, every one is Done or Archived (or owns a check failure, by `[board.actor] owner_source`, while `repo`'s `main` passes every required check, in any lane), its description declares no Start Criteria, and, under
  `[release] settle = "pin-bump"`, every dependency's pin bump has merged (the rule in Release).
- `deps_done_with_pr`: `deps_done` holds and `pr_ready` holds (the task cites a ready or merged pull request). A state lists it before `deps_done` to
  return a task that has a delivery to another lane than the one a task without one returns to.
- `deps_unresolved`: a dependency is not Done.
- `owner_stale`: the task's `source` starts with `[board.actor] owner_source`, no open task lists it in `dependencies`, and `repo`'s `main` passes every required check (`MainGreen`: the head commit's required checks roll up to passed; a pass is cached per commit, any other read is retried after 60 seconds, and a failed read reads as not green). A red or pending `main` closes nothing, because the check logs do not say which failure signature `main` still hits. A Ready state maps it to `CLOSE`, and the closing note names the green commit.
- `pr_unfinished_alive` and `pr_unfinished_dead`: a cited pull request is open and a draft, conflicting or failing a
  required check (a check still running is neither), and the board's `alive` command exits 0 (alive) or not (dead). A
  state maps them to different moves, so a Review task goes to its live holder and otherwise to Needs attention.
- `criteria_met`: an event the task is parked on arrived (below) and no dependency is open.
- `overdue`: a Waiting task is past its service level expectation: seven days from the lane's `entered` time, or
  two days past the latest `expect_by` its Start Criteria declare (an ISO date or timestamp; one with no zone is UTC).
  A task gated only on dependencies is exempt while every open dependency is in the working or review lane. A state
  lists it last, so a gate that holds wins, and maps it to a move into the attention lane; the actor sets the task's
  `## Needs attention` section to the age, the SLE and the gate, then `Blocker:`, `Options:` and the question the operator answers. A lane that waits on it also gets
  a deadline thread: each derivation arms the task's deadline, and the thread derives the task again when it falls, so
  no event has to wake it. A re-park, a new `expect_by` or a dependency's lane change re-arms it. 
A lifecycle machine whose phase state links a skill machine with `exits` (`submachines[].exits`, [Public surface](public-surface.md))
advances too. When the skill machine of the task's current phase reaches a state its link exits on, the actor publishes
the exit's event for that machine to `machine:events` as `starpulse/task-actor`, once per visit to the phase. A skill
machine the current phase does not link advances nothing, so a late final event of an earlier phase's skill cannot move
the task. The machine's `writers` name `starpulse/task-actor` for each such event.
The Board is such a machine, its phase the task's lane: the actor sends only the Board links whose every exit event
the Board's `writers` give to `starpulse/task-actor`, and ignores a skill
placement from before the task entered the lane, so a task sent back and merged again starts its next round clean.

A Waiting task waits on events, never on a polled check. `task park --until <subject>` stores each subject (an alert or a
deploy event, `starpulse.<board>.alert.<rule>.<event>` or `starpulse.<board>.deploy.<component>.<event>`) as a
`kind: event` entry of the task's Start Criteria. The actor keeps a `subject -> Waiting tasks` index and fires the state's
`criteria_met` event on the first event, of any of the task's subjects, that the bridge publishes for a machine event.
When a task enters Waiting, the actor reads each subject's latest event from the log (`latest`) and counts the subject
heard only when that event was recorded at or after the park, so an event that raced the park releases at once and one
from before it never does; an entry that sets `accept_met: true` accepts an event of any age. A subject the log cannot answer is refused at the park. A restart rebuilds the index from the records.

The board may withhold `deps_done` with reasons (`Board.holds`; the native board's `[board] holds` command, run
in the config's directory with `{id}` replaced, prints a JSON array of them, and output that is no such array holds the
task). The actor writes the reasons once as a comment on the task, and re-derives every held task when a task is created.

It keeps a `pull request -> tasks` and a `task -> dependents` index, built at start and kept current from lane writes. A
change to a pull request in the store, a lane write or a merged pin bump re-derives only the tasks it reaches. The
actor reads a store save as it happens, so a pull request's move does not wait for the pin walk of the projection that
saved it; the tasks held for a pin bump are re-derived after that projection. At start
it re-derives every open task once, so a pull request that merged while the server was down still moves its task. With
the actor on, the 30-second pass of Release does not start; the actor settles and releases on the same rules, so
`[release]` still names the settle rule.

The actor polls nothing: it sleeps until a task's next deadline (a Waiting service level, a claim) or an event. A fact moves a task only through an event its lane watches: a lane
write, a dependency change, a store save, a merged pin bump, or a machine event on a subject a Waiting task waits on (`event_seen`). Start recovery re-derives every open task once; a move it finds that no event
carried is logged as an error (`task actor: start recovery moved …, a move its lane's events missed`), and it flags once, as a task-actor comment `Flagged in Waiting:
<reason>`, a task waiting on a dependency nothing will finish, a task the board does not hold. A flag is not repeated while it is the task's latest flag, across restarts too. A task in
any other lane, Needs attention included, is not read.

A park that names `TASK-X#K` records the criterion the dependent needs (`dependency_needs`). A dependee's state change or
a criterion it checks re-derives its dependents. Once every criterion a dependent needs of an open dependency is checked,
that dependency counts as met: `deps_done` fires, and the release is one write that drops the dependency and its needs and
comments `Stale dependency TASK-X`. A lint refusal of the release is commented once on the task (a comment-only edit skips
the board's guards, so the comment lands) and the actor retries when the lint record changes.

A move from the working lane (the first resting State the lifecycle does not end in) to Waiting runs the board's
`parked` command once, with `{id}` replaced by the task's id, so a board can tell the session that holds the task. A
move from Waiting to Ready runs the board's `released` command the same way, so a board can resume the session that
parked the task. A task In Progress whose holder settles idle (the harness machine's `SESSION_SETTLED`, from the session's Stop hook completing) runs the board's `idle` command with `{id}` and `{verdict}` `confirm`, so a board can say whether the holder is busy; a nonzero `confirm` holds the task until the next move of a machine other than the harness settles it again, which the session's own activity cancels. An idle holder is then run with `resume`, so a board can wake it in place with its next step; after two resumes with no progress the next settle runs `escalate` first, and an `escalate` that fails moves the task to Needs attention. A task with an open criterion is nudged instead: its fourth idle settle with no criterion resolved since moves it to Needs attention. A `resume` that exits nonzero is sent again at once, as a holder whose resume was lost settles no more, and the third failure in a row moves the task to Needs attention; one that exits 3 means no session can receive the wake, so no later settle comes, and moves the task to Needs attention at once. A holder that settled while the task actor was down is treated as settling when the actor has indexed its tasks, unless a later harness event for the task shows it started again.
A move from the working lane to Review that the board refuses (an open review thread, a conflict, an unchecked criterion) publishes the `in-progress` machine event `REVIEW_REFUSED` once (reason in its data, so `task.<id>.review_refused` on the NATS bridge), until the task's facts change, so the holder is told why a ready pull request did not reach Review. A move from Review back to the working lane runs the board's `returned` command the same way, so a board can wake the session that delivered a pull request that turned draft or conflicting. A move to an archived lane runs the board's `archived` command once the same way, so a board can close the pull requests the archived task leaves open. A move to Done runs the board's `closed` command once the same way, so a board can file what follows the close, such as a
check that waits on time after the merge. A command that exits nonzero is logged; the move stands.

A task the board itself strands, rather than one waiting on an operator's choice, parks in Waiting on the task that owns
the fault when the board sets a `faulted` command. The stranding cases are a start the scheduler could not make, a session that no
session can resume, a session that keeps ending after its one resume, a holder's nudge that fails, and a task that left
Waiting with no session started. The actor runs `faulted` off its lock with `{id}` and `{verdict}` replaced by the task's id
and the fault as `<what>: <why>`, and reads the owner task's id from its output. It then adds that task to the stranded
task's dependencies and comments `Blocked: <task> <what>: <why>. Parked on <owner>, which owns the fault.`, so the derive moves
it to Waiting and the owner's Done releases it. With no `faulted` command, or one that fails or names no task, the task goes
to Needs attention with the reason as before. A command that files the owner when none exists keys it on the fault
without the task's id, so the same fault on any task meets one owner.

A write the board refuses is logged and counted, and is not retried until the task's facts change; checking the last
Definition of Done item of a task (`definition_of_done` in its record) is such a change, so a Done move a guard refused
for an unchecked item is tried again. A refused move to Done is also commented on the task as
`Held from Done: <reason>` and publishes `DONE_REFUSED` once (`task.<id>.done_refused`, reason in its data),
so the holder is woken on the refusal instead of the task sitting in its lane unread. A release to Ready
that a declared guard or the `validate` hook refuses is a defect in the task record: the task stays in its lane with a
comment naming the refusal, no operator question is minted, and the actor retries once the task's description, profile,
labels or dependencies change. A step that raises (a fact read, a comment read), a move with no route or into a closed
lane, and a write the board refuses for any other reason (a guard's `lint` refusal and a locked database are not faults)
park the task in Needs attention through the `ACTOR_FAULT` event, legal from every open lane and written only by
`starpulse/task-actor`. The reason opens `Task actor fault: <step>: <error>` and the log line at ERROR names the task, step and error;
the line under it tells the operator to fix the cause and move the task back to In Progress.
A task already in Needs attention keeps its lane and gets both lines ahead of its earlier text. The board draws an `actor error`
chip on the card of a task whose reason opens so. A fault is written once and never retried on a clock or health event; a
failed board write of it is logged and counted in `starpulse_task_actor_refusals_total`. `GET /metrics` carries:

- `starpulse_task_actor_refusals_total{reason}`: refused writes, one series per guard rule that refused, keyed by the
  rule's `key` (a slug of its reason), and `other` for a refusal no rule made (a hook, a store error).
- `starpulse_task_actor_latency_seconds`: a histogram of the seconds from the fact being observed to the write landing.
- `starpulse_task_actor_projection_seconds`: a histogram of the seconds each projection of the pull request store ran,
  the pin walk included.
- `starpulse_task_actor_handoff_seconds`: a histogram of the seconds from a store save to the actor reading it. The
  bounds run to 600 s, so a handoff or projection past the 10 s bound shows.
- `starpulse_task_park_release_seconds`: a histogram of the seconds from the first event a Waiting task was released on
  to the write that released it. The actor logs each event subject with the Waiting tasks it matched, and each release.
- `starpulse_task_merge_move_seconds`: a histogram of the seconds from a pull request's merge time to the actor's write
  that moved a task citing it. Start recovery yields to a pending store save, task change or move before it takes its
  next task, and a save derives the tasks citing a merged pull request first, so a merge during recovery lands in a
  bucket of 10 s or less.
- `starpulse_task_receipt_done_seconds`: a histogram of the seconds from saving a merge webhook (`pull_request`
  `closed`) to the actor's write that moved its task. The pulls consumer claims such a delivery ahead of every older
  pending one, and hands it to the actor as soon as the pull store holds it, before the refresh read; the actor's
  write holds only that task's recording lock, so no other task's board write delays it.
- `starpulse_task_actor_pin_held`: a gauge of Waiting tasks whose dependencies are done but wait for a pin bump to
  merge (`PinGate.waiting_on`); one that stays above 0 is a pin that never merges. Each such hold comments the pull request
  and pin it waits on once. Only a cited pull request that can be the dependency's own delivery counts: one whose
  branch or title names another task is a reference.
- `starpulse_task_actor_recovery_finished`: 0 until start recovery has derived every task, then 1.
- `starpulse_task_actor_merged_review_waiting`: a gauge of Review tasks whose cited pull request merged, whether or not the
  actor has tried or been refused a move for them; compare with the moves landed, the `starpulse_task_actor_latency_seconds_count`
  rate. The actor reads its lock-held series (this one and `pin_held`) with a 2 s timed acquire and
  omits them when it cannot, so a stuck turn never blocks the scrape; the recovery gauge needs no lock.
- `starpulse_task_actor_idle_holders`, `starpulse_task_actor_idle_holder_seconds` and `starpulse_task_actor_ready_tasks`:
  the In Progress tasks whose session reads settled (the harness machine not `active`) with no event to wait on (no open
  pull request with pending checks, no awaited machine placement), the seconds the oldest has been settled (0 when none),
  and the Ready tasks. They are read from the board at each scrape, so a resume that wakes the session clears them. The
  `starpulse-idle-holders-block-ready` rule notifies when the oldest has idled over an hour, they are half or more of
  `starpulse_board_in_progress_tasks`, and Ready work waits; it never moves a task.

A hold or flag comment lists the first three reasons and a count of the rest, and is clipped to 4000 characters
(`COMMENT_CAP`), so a failed probe of hundreds of references does not write a 26 KB comment.

Each move the actor writes names `starpulse/task-actor` on its `board:lanes` entry: the Delivery worker records the lane
change when it writes it, in the history and the log in one transaction, and the file scan that places the change
later finds the lane recorded. The same holds for every write `serve` makes on the native board, under the request's
actor. A change no such write recorded (a file edited by hand, a write that does not say the lane it
set) is recorded at its placement as `external`. `GET /metrics` carries `starpulse_board_lane_unattributed_total`, a
counter of the `board:lanes` entries any process appended since `serve` started that name no actor.


## Conformance violations

`serve` judges every move against the machine that draws it, as `starpulse conform` ([Replaying history against the
machines](cli.md#replaying-history-against-the-machines)) does on the stored history, and `GET /metrics` carries two
counters for each machine the feed draws:

- `starpulse_machine_conformance_events_total{machine}`: the moves judged.
- `starpulse_machine_conformance_violations_total{machine}`: the moves no transition declares.
- `starpulse_machine_event_occurrences_total{machine,event}`: the recorded occurrences of each event the machine declares, 0 until one arrives.
- `starpulse_conformance_replay_remaining_entries`: the entry ids of `board:lanes` and `machine:events` past the monitor's cursors, up to the heads it found at start; falls to 0 as a replay reads on and stays 0 after, absent while the heads are unreadable. The worker keeps the text every 10 seconds before it has caught up, so a value that does not fall means the replay is stuck.
- `starpulse_board_lane_entered_total{lane}`: the moves into the Board's done lane and into `archived`, a task's first sight in one included, 0 until one arrives. A task entering a lane again counts again, so `increase(...[1d])` is the day's Done count. The counts are saved in the same checkpoint, so a restart neither recounts nor drops a move.

The `board` machine is judged on `board:lanes`, every other machine on `machine:events`. `serve` counts every entry
the log still retains and follows new ones after, saving the counts, each task's lane and each judged key's states every
5 minutes in the `conformance:checkpoint` setting. A restart resumes from that checkpoint and reads only the entries
appended since, so its counts go on from the last ones rather than starting at 0, and an entry pruned from the log
since the checkpoint stays counted. With no checkpoint, one of another version or of other machines, or one whose last
entry of a stream the log no longer retains, a restart recounts the retained entries, and the pruned ones leave the
count. The count of retained entries runs on a background thread, so the
banner does not wait on it: until it finishes, a scrape shows the counts so far. Every machine has both series from the
first scrape, at 0 until a move arrives. The first lane seen for a task is placed unjudged, because the log keeps no
earlier history; the stored-history replay judges it from the initial state. Guards are not judged.

## History recorder lag

The `contexts` child's flow-metrics recorders copy each stream's entries from the event log into the history store.
`GET /metrics` reports how far behind each copy is: `starpulse_history_recorder_lag_seconds{stream}` for `machine:events`
and the verdict stream, the age of the oldest entry past the stream's saved checkpoint, 0 when
the copy is caught up. A value that keeps growing means the recorder has stopped, and `starpulse task trace` shows a
shorter path than the live machine holds. The scrape omits the series when the log cannot be read.

`starpulse reload` that re-executes `serve` replies first and re-executes after. A caller that has timed out and left
does not cancel the re-execution: the supervisor has halted and ended its non-socket children by then, so skipping the
re-execution would leave `contexts` stopped.

## Event log archive

Before the sweeper deletes an event-log row it appends the row to a gzip JSONL file under `event_log_archive_dir`, one
file per UTC day of the row's `at`, named `YYYY-MM-DD.jsonl.gz`. A later pass that prunes more of a day appends to that
day's file, which is then several gzip members in a row; `gzip` and DuckDB read them as one stream. A pass writes and
fsyncs a batch of rows, 1000 at most, before it deletes that batch, so a write that fails (disk full, directory not
writable) deletes nothing and logs the failure, and the next pass retries. A crash between the write and the
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
- The snapshot holds no Ledger row. A Ledger's rows are `POST /graphql` reads: `occurrences(event, offset, limit)` is
  `{rows, more, total}`, newest first: the `limit` rows (default 50, at most 100) after the first `offset` (default 0),
  whether older ones remain, and how many rows the Ledger holds, each an `Occurrence` (a `LedgerRow`, `runs` and `fails`
  as JSON; `child` marks another repository's merge, whose `appliedBy` is the parent merge's key or null until one has).
  The page sends the count of rows it holds as `offset` and drops a key it already holds, so a row that reached the head
  between reads repeats rather than skips; none is older than 24 hours; a negative `offset` or a `limit` outside 1-100 is
  a GraphQL error; an event no
  workflow is tied to is null. A page with a Ledger open runs `subscription { occurrenceChanges(event) }`: graphql-sse
  frames whose first `next` is `{head: true, rows, more, mergeStrip, mergePins}`, the newest 20 rows and whether older ones remain, and whose
  later ones are `{head: false, rows, mergeStrip, mergePins}`, the rows that are new or differ and the strip and pins whole (a change to either alone sends no rows), so a Ledger no page has open costs no frame; an
  unknown event is 404. `mergeStrip` (snapshot, the `ledgers` event, and the `MERGED` page and its changes; null with no workflow tied to `MERGED`) counts the whole day without the
  rows: `{since, bucket, buckets}`, 96 buckets of 900 seconds from `since`, each
  `{merges, failed, reruns}`: merges landed, those holding a failed run, and forced reruns started (a run whose
  `[runs.commit]` `force` parameter is set and not `0` or `false`). `mergePins` (same carriers; empty on any other event) lists the pinned
  merges of the last day that the newest page leaves out, so a failure waiting on its cue is never paged out of sight.
- A run whose parameters name an occurrence under `[runs.commit]` (`after` for a merge's commit, a full or abbreviated
  sha; `task` for a task) pairs with it and is not `inferred`. A run that names an occurrence StarPulse does not hold pairs
  with nothing.
- Any other run of a tied workflow pairs with the newest occurrence before it started and is `inferred`; its `ambiguous`
  counts the older occurrences that landed since the workflow's previous run, any of which it may equally be for. Of several
  inferred runs for one occurrence the earliest wins, and a keyed run outranks them.
- A workflow's `recent` runs (`Dag.recent`, the last day's, with their parameters) are read from the runs adapter for tied workflows
  only, and are left out of the `dags` the page draws.
- A failed run of a cued workflow *pins* its occurrence: the row carries `fails` (`{<instance>/<workflow>: {runId, step,
  startedAt, finishedAt, resolves, resolved}}`) and `pinned` while any failure is open. The cue's `resolves` decides the
  clearing run, which must have started after the failure and succeeded: `next`, any such run of that workflow; `forced`,
  one whose `[runs.commit]` `force` parameter is set (not empty, `0` or `false`) and which covers the failure, naming no
  commit or task or an occurrence at least as new (a commit the Ledger does not hold covers nothing). A failure is
  tracked apart from the run drawn for the occurrence, so a green plain retry of the same commit does not clear a
  forced failure. A cue with no `resolves` rule, or an event no cue names, takes `next`. An instance with no `force`
  key never clears a forced failure.
- A pin lasts as long as StarPulse can still read the failed run: the last day of runs (`recent`) and the window of
  merged pull requests and lane entries. An older failure drops out of the Ledger.
- A `[[repos]]` entry names a repository whose merges apply through the parent's pin bump. Its `MERGED` rows take no run
  and carry `appliedBy`: the `key` of the first later merge in another repository whose submodule pointer at `path`
  contains the merge's commit (read through GitHub), or `null` while no such merge exists. That merge's row lists what it
  applies in `applies`. A pin bump appears only when a task cites its pull request.

## Cold done tasks

A task is hot for 24 h after it enters `done`, then cold: the board feed holds only its `id`, `state` and
`entered` time, and `GET /api/snapshot` omits it. A hot task keeps its record in `flows`; a lane change out of `done`
(a reopen) reloads the cold task from its board file onto its new lane within that one change, and cooling itself
publishes nothing, so a page keeps a card until it reloads. The page's snapshot (`/api/snapshot`) is slim:

- `flows` carries open and hot done tasks, each without `description` and `criteria` (read them from
  `GET /api/task/<id>`) except an In Progress task, which keeps both live; an active task keeps its `moves` inline; a Done task is a slim dot (`id`, `title`, `state`, `model`, `labels`, `milestone`, `created`, `entered`), here and in
  the `task` delta that moves it, for the Star Map's black hole and the counts (`done_dot` in `board/model/feed/shared.py`);
- every other flow names its states and events once in `names`, and each task's `trail` is points `[state, event, dt]`
  indexing it (a sourced machine's step adds its `id` as a fourth member): `dt` is the whole milliseconds since the step
  before, the epoch for the first. A `move` delta carries `names` for its own agent's trail, which the page interns into
  the flow's. A step's `data` is not sent (`_interned` in `views/model/encoding.py`);
- `archived_today` counts the tasks archived since local midnight by `archived_at`, the time of a task's last `Archived` event
  (one range of `ix_starpulse_tasks_archived_at`, `archived_since`, migration 0083), never `updated_at`, which any later write
  to an archived task moves; an archived
  `task` delta carries the new number;
- `settled` keeps the tasks created or settled in the last 24 h, and `milestone_done` (`{milestone: count}`)
  counts every settled completed task by milestone;
- `/api/snapshot`, `?view=full` and `/api/flows` serve this one stored body: the CLI verbs read `/api/flows`, `/api/jobs`,
  `/api/task/<id>` and the routes above, and a verb that needs a task's description or criteria reads `/api/task/<id>`.

`GET /api/done[?before=<entered>][&limit=20][&milestone=<id>]` returns `{tasks, more}`, the next page of cold done tasks, newest done
first, each `{id, title, state, model, labels, milestone, type, follows, entered}`, its card fields from the read model when the feed has one (no board file is opened), else read from the board on request. `before` is
the `entered` of the last task held; `limit` is 1-100; `milestone` keeps that milestone's tasks. A board that cannot read a task answers 404. A cold task has no
`moves`, so moving it is a 409; `task show` and the held stream read it whole through its record.

## Machine rows

The machines entered from an open machine (the In Progress one at the top) are its rows, newest activity first: a row is
as recent as the newest task of the machine and every machine nested below it, ties break by name, and a machine with no
task comes last. The snapshot's `flows` carries every machine and its ties, so the page draws every row from it and
pages nothing. A machine's **ties** are declared (a `submachines` link on another machine's state) or a DAG launch; a
machine is nested only where a file declares it. Each machine file declares its `type` and `parents`, and the loader
refuses a file whose `parents` differ from the machines whose `submachines` name it. `POST /api/machines` and
`GET /api/machines/{name}` show that config.

The page scrolls the rows under the fixed top by the wheel, Page Up and Page Down, the arrow keys, Home and End and a
draggable thumb, with `↑ back to newest` once scrolled; the rows are drawn only while in view. The 24 h strip under the rows draws a tick per
entry, coloured by the state it was entered from (amber for a workflow launch), shades the rows in view as one
stretch, and a click on a tick scrolls to its row. A click on a state of the top scrolls to the first machine it
opens and picks it out; Escape steps back from the card, then the picked row, then the scroll to newest. A click on a task pins it and narrows the rows and the strip to
the machines it holds a session in (`N machines holding <task>`); closing its card restores every row.

## First install

`starpulse init [--dir DIR] [--harness claude-code]` scaffolds a first install: `starpulse.toml` (a native `[board]` with
one `[[board.guards]]` rule, a `[board.actor]` table, a `[scheduler]` table and a `[[producers]]` entry reading `STARPULSE_TOKEN`), `board.yaml`
(five States, every role declared; a created Task waits in Backlog, which `task dispatch` takes a session from, and the task actor pins it) and the harness's telemetry settings (`.claude/settings.json`). It never writes a
token, and writes nothing, naming the file on stderr and exiting 1, when any of the files exists.
