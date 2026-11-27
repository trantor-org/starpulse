# Connect sources

Each source moves tasks or runs through a machine on the page: agent sessions, scheduler runs, pull requests.

## Show your Claude Code sessions

Run the receiver beside the server, then start Claude Code with its log export pointed at it. The receiver publishes
through the event log of the history database the server reads, so give it the server's `--config`
(`starpulse-history.sqlite` beside that file; without one, the working directory's). Port 4318, OpenTelemetry's
default, is often taken: `--port` moves the receiver, and the endpoint below follows it.

`starpulse serve` runs the receiver itself, as a thread of its `contexts` child, when `starpulse.toml` holds a
`[claude_code]` table (`host`, `port`, `redactor`; see [Serving](serving.md)): it restarts with that child under its
memory limit and closes its port when `serve` stops, and no second process or unit is needed.

```sh
uvx --from starpulse python -m starpulse.runtime.claude_code --config starpulse.toml --port 4319

claude --settings '{"env": {
  "CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_LOGS_EXPORTER": "otlp", "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
  "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4319", "OTEL_LOG_TOOL_DETAILS": "1",
  "OTEL_RESOURCE_ATTRIBUTES": "vcs.ref.head.name='"$(git branch --show-current)"'"}}'
```

A launch also appends `claude_code.entrypoint=<cli|sdk-cli>` to `OTEL_RESOURCE_ATTRIBUTES` to name how it started. StarPulse copies it onto each signal and into the `entrypoint` field of session rows, beside
`first_request_tokens`, the prompt tokens (input, cache read and cache write) of the session's first main-thread request, null when it made none. A session whose launch sets no entrypoint, such as a Desktop one, has it empty.

A row's `role` is the furthest of the `[analytics]` table's `phases` (skills in lifecycle order) the session loaded on its task, `other` when it loaded none or none are declared, and its `agents` sum each subagent type's tokens (the `agent` of a side request that names one), so spend reads per phase and per qa lens.

An eval or judge run that is not work names itself by appending `<eval_attribute>=<purpose>` to `OTEL_RESOURCE_ATTRIBUTES`, the attribute the `[analytics]` table's `eval_attribute` names (with none, no run is an eval).
StarPulse copies the purpose onto each signal and into the `eval` field of session and step rows, and the trace-cluster
view leaves those sessions out.

Pass the variables through `--settings`, not the shell: an `env` block in your user-level `settings.json` overrides
`OTEL_*` variables set in the shell, so a shell export can leave a session exporting somewhere else. The session
moves the task its branch names (`TASK-<n>` in the branch), so start Claude Code on that branch.

The receiver decodes each export but publishes only which session moved, on which event and when; prompt,
reply and tool text is never stored.

## Fold what each session did

The same receiver also reads each Claude Code export for what a session did, and the server folds each batch into
per-session rows as it arrives (the sessions sink reads those rows; no route serves them).

A session is one harness session id; it has one row per task it worked, found from the branch the export names
(`vcs.ref.head.name`), or a command or `Skill` call that matches an `[analytics]` `claims` pattern claims
one. Every step after a claim belongs to the claimed task, until the next claim or switch, and the steps before a
session's first claim or task-naming switch, when its launch branch names no task, belong to that first task.

What the server keeps of a session is three folds, advanced as each batch of its signals arrives and stored in
`starpulse_signal_folds` beside the session's `ledger` row (the settled tail and the state the folds resume from):

- `steps`: one row per model request, with its model, effort, token counts, the activities and shell commands of the
  tool calls it owns, the skill in force and whether it is an eval step.
- `cost`: one row per task and skill of those steps: the steps, a subagent's, the wasted ones, the seconds and the
  peak context.
- `spend`: the captured, non-auxiliary steps that belong to a task, with whether each edits, each task's first claim
  time and its compactions; the task detail's `spend` field combines them.

A turn is the signals that share a Claude Code `prompt.id`. A prompt is labelled `injected` when its opening
matches an `injected_openings` prefix and `human` otherwise; with an `[analytics.labeller]` configured, a `human`
Claude Code prompt's text is also sent to that typed-decision endpoint, which names its intent (one of the table's
`criteria`, else `unsure`). The label is kept on the prompt signal and the text never is. An endpoint that is
unreachable, slower than its `timeout` (default 2 s) or answers nothing usable leaves the label empty and ingest goes
on.

What an export cannot say is absent rather than guessed: Claude Code exports no user interrupt.
A signal at or before its session's settled cut is dropped, and a session in flight when the folds started advancing
at ingest begins from its first later signal. No signal is kept: the server folds each batch into the rows above and
holds nothing to refold, and the folds table has no prune, so it grows with the sessions.

One signal is one step of the record the steps-per-clean-completion ledger counts: a `request` is one model call, with
its model, effort, duration and the four token counts, and a `compaction` names its trigger. Two fields say whose step
it was and whether to count it, and a third holds a command:
- `agent`: the subagent that made a `request` or `tool` step, from the export's `agent.name` or, for Claude Code, its
  `query_source` when that names a subagent. Empty for the main thread. A
  subagent's steps carry the parent's session id, so they count toward the task that spawned it.
- `captured`: false for a stored signal of a harness the ledger does not cover, so a ranking leaves it out. A signal
  stored before the field existed reads as captured only when its harness is Claude Code.
- `command`: a Claude Code shell result's command, empty otherwise. It is kept only when the adapter runs with
  `--redactor MODULE:FUNCTION`: the function filters the text, a heredoc body is replaced by
  `[heredoc length=<bytes> sha256=<hex>]` before the function sees it, and a function that raises keeps no command. No
  exit status is stored, because the export carries none; `ok` is the result's `success` and `seconds` its duration.

## Report each task's spend by phase

The `spend` field of a task in `POST /graphql` (168 hours) is one row per phase of
that task over its model requests, a subagent's counted to its task, an uncaptured session left out, by the phase's first
step; it is empty for a task with no spend in the window, and null with an error when the window is longer than the
folded history or the instance receives no telemetry. Its columns:

- `task`, `kind`, `size`: the task and its board labels `kind-<kind>` and `size-<n>`, null when it has none.
- `phase`: `claim`, `implement`, `qa`, `deliver` or `review_fix`. The skills `qa`, `deliver`, `review-fix` and
  `cr-triage` set their phase. A step before its session's first naming signal (claim or task branch) bills to no
  task. Every other step is `claim` until the step that carries the task's claim, or the first
  step of the task that edits a file (`Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `StrReplace`) when no claim is in
  the window, across all its sessions in the window, and `implement` after it; a task with no edit and no claim in the
  window is all `implement`, so a window that starts mid-task does not bill its work to `claim`.
- `steps`, `side_steps`: model requests and the subagents' share of them.
- `input`, `output`, `cache_read`, `cache_write`: the phase's tokens. `wte` weighs them as the provider prices them
  against one uncached input token: a cache write 1.25, a cache read 0.1, an output token 5.
- `peak_context`: the most input, cache-read and cache-write tokens one request held. `compactions`: the compactions
  that fell in the phase, a compaction counted to the phase of the step before it.
- `models`, `first_at`, `last_at`: the models used and the epoch seconds of the phase's first and last step.
- `profile`: `<model>-<effort>` of the phase's first main-thread step (its first step when a subagent made every
  step), each `unknown` when the harness recorded none; the key per-profile norms group by.
- `task_wte`: `wte` over the task's phases in the window. `phase_norm_wte`: the median `wte` of the tasks of its kind, size and
  `profile` that ran this phase; a profile with under 5 such tasks falls back to the kind and size cell, and null under 5
  there. `norm_profile`: the profile of the cell used, `mixed` for the fallback pooling every profile, null with no norm. `phase_above_norm`: `wte` is over 3 times it. `norm_wte`: the sum
  of `phase_norm_wte` over the phases the task ran (null when any is null), so a task that ran qa is weighed against
  peers' qa. `above_norm`: `task_wte` is over 3 times `norm_wte`.

Blind spot: `starting-task` stays in force through the build, so the skill alone cannot split `claim` from `implement`;
the first edit does, and a task worked by hand with no skill loaded is still placed by it. A task with no labels has
no norm. A `batch-umbrella` task is in no norm cell, so its fixed size-8 label leaves size 8's norm to the tasks that do
one job (90 of 116 size 8 execute tasks in 192 hours, median 1.29 M WTE against 3.81 M for the other 26, above size 5's
2.72 M). Its own norm is per phase the sum of its members' kind × size phase norms, read from the kind and size its
`members` record keeps for each; one member whose cell has no norm leaves it null (`no_norm_reason` "a member has no
norm").
## Group recurring work

The same signals say what each session did, not only how long it took. A tool call is lifted to *activities* with no
argument, so work recurs across sessions: a non-shell tool is its bare name; a shell call is each statement's leading
command, as `git status`, `gh pr view`, `make test`, `bin/<script>`, `ssh <user@host>`, `shell_read`, `shell_search`,
its binary name or `shell_other`. An export that carries no command (`OTEL_LOG_TOOL_DETAILS` off) leaves a shell call
as its tool name. Claude Code caps each `tool_input` string over 512 characters, so a shell call reads its command from
`tool_parameters.full_command`, which is whole, and falls back to `tool_input`. `uv run` is unwrapped through its flags,
including the directory after `--project` or `--directory`. The path a file tool read or wrote is kept raw and cut at read time to an *area*, its first two
components below an `[analytics]` root. A session no branch or claim ever ties to a task has steps with no task.

Nothing in the server groups those activities now: the offload and correction reports read the stored `steps` rows in
process and group them themselves.

## Save GitHub webhook deliveries

A `[github]` table (`secret_env`, `organisation` or `repositories`, `inbox_files`, `max_body_bytes`, `host`, `port`, `reconcile_token_env`; see
[Serving](serving.md)) makes `serve` run a listener in the `contexts` child for a GitHub App's webhook. Without the
table none runs. Point the App's webhook URL at the listener, set its secret in the environment variable `secret_env`
names, and the listener answers each POST in this order:

1. A missing or non-numeric `Content-Length` is 400, a body over `max_body_bytes` is 413, and a body that stops
   arriving within 15 seconds is 408.
2. A missing or wrong `X-Hub-Signature-256` over the raw body is 401; nothing is parsed before it matches.
3. An `X-GitHub-Event` outside the allowlist is 204. For an allowed event, a body that is not a JSON object, or a
   request with no `X-GitHub-Delivery`, is 400, and a repository outside `organisation` and `repositories` is 204.
4. One transaction inserts the raw body into the `github_inbox` table keyed by `X-GitHub-Delivery` and commits, then
   the answer is 202. A delivery already saved is 202 too, and adds no row.
5. A commit that fails is 503, so GitHub keeps the delivery as failed.

The inbox lives in the main store (the `github_inbox`, `github_inbox_state` and `github_reconcile_state` tables, created by
its chain). With `inbox_files` (a glob for the old inbox database files) `starpulse migrate` copies their rows into the
store once and leaves the files. If the variable `secret_env` names is unset or empty, or the address is taken, the `github` context fails to
start, and the `contexts` process logs why and retries it with the usual backoff; no request is answered meanwhile.

`GET /metrics` on the listener serves `starpulse_github_deliveries_total{event,verdict}` for Prometheus, with the
verdicts `accepted`, `duplicate`, `bad_signature`, `oversize`, `ignored`, `foreign_repository`, `invalid`, `timeout`
and `error`. It shares the listener's port without authentication: keep `host` on loopback, or have the proxy that
faces GitHub forward only `POST`.

### Turn saved deliveries into machine events

With a `[github]` table, an enabled `[bridge]` and a `[[producers]]` entry named `github` (`token_env`, `machines = ["github-pull-request"]`,
`actors = ["github"]`), `serve` also runs the `github-events` context: the `events` consumer, which reads the inbox and
publishes one CloudEvent per pull request fact to the bridge's JetStream ingest (`ingest.<board>` on the `[bridge]`
`port`) as the `github` actor, and the `bridge` context applies it. Without the bridge, the entry or its token in the environment the context is
absent or fails to start, and the inbox keeps every delivery.

1. Each consumer keeps its own state per delivery in `github_inbox_state`: `pending`, `done`, `skipped` or `dead`.
2. `pull_request` opened, reopened, closed and merged give `PR_OPENED`, `PR_REOPENED`, `PR_CLOSED` and `PR_MERGED`, and
   an edit that changed the body gives `PR_EDITED`, which asks the store to read that pull request from GitHub;
   `check_suite` completed gives `CHECKS_PASSED` or `CHECKS_FAILED`, and a failed `check_run` gives `CHECKS_FAILED`. The
   event id is a SHA-256 over repository, number, event type and the head or merge SHA (the check suite id for
   `CHECKS_*`), so a repeated fact collapses on the ingest. The subject is the unarchived task whose references hold
   the pull request URL.
3. A failed attempt waits `min(2**attempts, 300)` seconds. A 400, 403 or 413 answer is `dead` at once, and so is the
   tenth failure. A pull request with no linked task is retried the same way, then `skipped` as `no-task`; a bot's
   pull request is skipped as `no-task` at once.
4. The `pr-checks` rollup reads GitHub once per head: its open pull requests and posted checks, kept in memory and
   updated by each later delivery, so a restart costs one read per head. A check whose payload names only unlinked pull
   requests reads nothing. A rate-limited read (403 or 429 with a reset time) leaves the delivery `pending` until the
   reset with no attempt spent, and no read is made before then.
5. Done and skipped rows are purged after 7 days, with the inbox rows no consumer still needs.
6. `starpulse github requeue|dismiss <delivery_id> [--config]` settles a dead row: `requeue` makes it pending with its
   attempts spent anew, `dismiss` skips it and keeps its last error. A row that is not dead exits 1.
7. `starpulse github retire --before <epoch seconds> [--consumer] [--config]` skips the consumer's pending rows never
   tried and saved before then, but a `pulls` merge (`pull_request` `closed`), 5,000 rows a transaction, so the listener saves between them: a backlog the consumer
   would only claim to re-read pull requests the reconcile reads anyway. A merge webhook does not wait on such a
   backlog: the `pulls` consumer claims a `pull_request` `closed` delivery ahead of every older one.
   The `pull-reads` consumer claims only `push` and `repository_ruleset` deliveries and makes their GitHub reads on a
   thread of its own, so a push's compare per open pull request never holds up a `pulls` write.

The page's `/metrics` serves, per consumer, `starpulse_github_pending_rows{consumer}`,
`starpulse_github_oldest_due_seconds{consumer}` (the age of its oldest pending row that is due) and
`starpulse_github_dead_rows{consumer}`, the dead rows it holds until `requeue` or `dismiss` clears them, and
`starpulse_github_oldest_check_seconds{consumer}`, the age of its oldest pending `check_run`, `check_suite` or `status`
delivery whose last attempt did not end `no-task` (0 with none), which the `starpulse-pr-checks-stalled` alert reads; the listener's own `/metrics` serves the same.

7. A consumer with no row starts at the newest delivery, not the whole inbox: its first claim anchors there with a
   `skipped` row and every claim seeds only past its oldest own row. `SqlQueue(..., backfill=N)` makes the first claim
   seed the newest `N` deliveries as `pending` instead; no consumer opts in today. A claim never seeds a delivery saved
   more than 7 days ago: the purge dropped that consumer's row once done, and a dead row pinning its floor would
   otherwise bring a week of old deliveries back as `pending` ahead of the fresh ones after a restart.

### Reconcile the inbox against GitHub

With `reconcile_token_env` in `[github]` (the environment variable that holds a token able to read the accepted
repositories' pull requests and checks), the sweeper's `github` kind runs
a reconcile pass on each sweeper pass (`[sweeper] interval_s`); no thread or timer of the `github-events` context
runs it. A pass samples each list it reads and counts each redelivery asked and each row inserted as a correction
(`starpulse_sweeper_samples_total` and `starpulse_sweeper_corrections_total` with `kind="github"`). GitHub accepts only
the App's own JWT on `/app/...`, so the delivery reads and redeliveries sign each request with a nine-minute RS256 JWT
minted from `GH_APP_ID` and the key file at `GH_APP_PRIVATE_KEY_PATH`, never with `reconcile_token_env`'s token. With
either unset the delivery half fails each pass, logged and naming the variable; the pull request half still runs.

1. It pages the App's deliveries back from a stored cursor (the newest `delivered_at` it has handled; the first pass
   reaches back 7 days) and asks GitHub, with `POST /app/hook/deliveries/{id}/attempts`, to redeliver the newest attempt
   of each GUID with no `github_inbox` row, unless one of its attempts was answered 2xx (the listener saved it, or chose
   to ignore it as another event or repository). A redelivery that fails too is a new attempt past the cursor, so the
   GUID is asked again each pass until one attempt is answered. The listener's dedup makes a repeat harmless.
2. For each accepted repository (the listed ones, and the organisation's unarchived ones) it lists pull requests newest
   updated first until it reaches its `pull-rows:<repository>` cursor. Each closed pull request becomes a `pull_request`
   row with `delivery_id` `reconcile:<repository>:<number>:<sha>:closed` (the merge SHA when merged, else the head SHA), and
   each check suite on the head of a pull request in the list that finished while it was open a `check_suite` row (a
   `check_suite` webhook names no closed pull request, so a suite finishing after the close is no missed push) with `delivery_id`
   `reconcile:<repository>:<number>:<head sha>:<suite id>`. Both have `source = 'reconcile'`, are shaped like the webhook body
   that would have reported them, and travel the consumer path above. A `pull_request` row carries the listed pull request
   whole, with `merged` and a top-level `number` added, so the relay reads its closed time and refs as from a webhook.
   A suite a `check_suite` webhook for the same suite id already reported counts as reported even when the webhook named no
   pull request (the checks path finds a suite's pull requests by its head). A row for a fact younger than a minute
   (`SETTLE_S`) is inserted but not counted, as its webhook may still be in flight. A row for a fact a delivery already reported
   collapses on the event id. A pull request in the list the PR store lacks, or holds with an older `updatedAt`, also
   gets a `pull_request` row with action `reconciled` and `delivery_id` `reconcile:<repository>:<number>:<updated_at>:updated`
   that carries the listed pull request whole; it names no fact, so the `events` consumer skips it, and the `pulls`
   consumer writes the record from it whether or not a task cites the pull request.
3. Every list is read with the ETag it last returned (`If-None-Match`): a 304 spends no rate limit and leaves the
   cursor and the inbox as they were. No call is GraphQL. Pull requests are handled oldest first and the
   `pull-rows:<repository>` cursor is saved after each one a newer one follows (a tie is never split), so a pass that failed resumes after the last pull request it
   handled; a cursor's ETag is saved only after everything its list covers was handled. The inbox is SQLite in WAL mode
   with a 30-second busy timeout, so the pass, the listener and the inbox's readers wait on each other's locks rather
   than failing.

The pass keeps `starpulse_github_redeliveries_total`, `starpulse_github_reconcile_rows_total{kind}` and
`starpulse_github_reconcile_cursor_lag_seconds{cursor}` (`deliveries`, `pull-rows:<repository>`) in its process, as
`Reconciled.exposition()`; the sweeper worker keeps them beside its own counts for `/metrics`. The sweeper counts inserted rows only as the kind's
corrections, since a redelivery is GitHub pushing the delivery again, the recovery path working.

## Report runs from any scheduler

A cron line, a systemd unit, an engine that can only send webhooks (Cronicle, Rundeck, a GitHub `workflow_run` relay) or
a producer on another host reports a run as a Step CloudEvent to the same ingest that takes machine events
([Post machine events as CloudEvents](#post-machine-events-as-cloudevents)). Declare it as a `[[producers]]` entry; a
producer that only reports runs leaves out `machines` and `actors`, needs no adapter, pulls nothing and starts nothing (set `start_url` on its
`[[runs]]` instance for the page's `Run in <runner> ↗` link):

```toml
[[producers]]
name = "cron"
token_env = "CRON_INGEST_TOKEN"
```

Name the token's variable with `--token-env` and emit the event:

```sh
starpulse event emit --source cron --type StepStarted --subject 2026-10-03 \
  --token-env CRON_INGEST_TOKEN --data workflow=nightly --data status=running
```

A Step event is `type` `StepStarted` or `StepFinished` with no `machine`. `subject` is the run's id; `data` holds the
`workflow`, the `status` (`not_started`, `queued`, `running`, `succeeded`, `failed`, `aborted` or `skipped`) and, for a
step's own entry, `step` and optionally `depends`, the steps it waits on. A run's own entry names no `step`. The page
draws an accepted event as `pushed/<source>/<workflow>`. A workflow no adapter lists is drawn from the step graph its
events add up to, and that graph is kept in the history store across restarts. Each step of it also serves its
`last` outcomes, up to five, newest first; a pushed workflow serves no `schedule` (empty), `stats`, `rerun`, `precondition` or
`lock`, which the events do not carry. A token writes only as its own
producer: a missing or wrong token answers 401, another producer's `source` 403, an event the contract does not allow
400, and none of them writes anything; the other answers are the machine events' table below.

A qa lens's verdict rides the ingest too: `type` `VerdictRecorded`, no `machine`, `subject` the task and `data` holding
the `lens`, the `round` (an integer from 1), the `outcome` (`PASS` or `CHANGES`) and optionally a `reason`. A verdict
missing a lens, round or outcome answers 400 and writes nothing. Every verdict is kept, per lens and round, by the
history store, and the feed publishes each as a `verdict` event (`task`, `lens`, `round`, `outcome`, `reason`, `at`).
A lens that has sent no verdict has no row, so a reader never counts it as `PASS`.

A commit that broke the default branch is a `postmortem` doc, linked from the task that broke it through the task's
`documentation` list. StarPulse keeps no breaking-change event, table or route: `BreakingChangeRecorded` and
`BreakingChangePostmortemed` answer 400 like any unknown type, and `/metrics` counts the postmortems with the other docs
(`starpulse_docs{type}`).

## Post machine events as CloudEvents

A build job, a bot or any service posts a lifecycle machine's event as a [CloudEvents](https://cloudevents.io) 1.0
event, through `starpulse event emit` to the JetStream ingest or over Connect or gRPC. Declare the producer and set its
token in the server's environment; the Connect ingest answers 404 until one is declared:

```toml
[[producers]]
name = "ci-bot"
token_env = "CI_BOT_TOKEN"
machines = ["delivery"]
actors = ["ci"]
```

```bash
starpulse event emit --source ci-bot --type BUILT --subject PROJ-1 --machine delivery --actor ci --data sha=abc123
```

`starpulse event emit` builds `starpulse.contracts.CloudEvent`, the model the ingest reads, and publishes it to the JetStream ingest of the `[bridge]` in `--config` (default `starpulse.toml`) with the token
in `STARPULSE_PRODUCER_<SOURCE>_TOKEN`. It exits 0 once the stream holds the event and 1 when the server is unreachable.
The `bridge` context applies the event with the ingest's checks (token, machines, actors), so one it refuses is logged
there, not answered to the emitter.

A producer that reports a run system's Step events may set `adapter` to that system's run Adapter type
(`adapter = "github_actions"`): its events then carry the system's own status label in `data.status`, and the ingest reads it
through the adapter's `status_of`, so a hook posts the label as it is and an unknown label is a 400.

A batch (Connect `PublishBatch`) takes up to 200 such events. The attributes map to a
`machine:events` entry:

| CloudEvents | Entry | |
|---|---|---|
| `id` | `event_id`, as `<source>/<id>` | posting an event again writes it once |
| `source` | the producer | must be the token's own producer `name` |
| `type` | `event` | an event the machine declares |
| `subject` or `run` | `task` or `run` | exactly one of the two |
| `machine`, `actor` | the same | extensions; the machine must be drawn, the actor one of the event's declared writers |
| `time` | `time` | optional RFC 3339 with an offset; the server's clock when left out |
| `data` | `data` | optional JSON object, at most 8 KiB as JSON |

A batch is checked whole before anything is appended, so one refused event writes none of them. An accepted event is
a `machine:events` row like any other: it moves the task on the page and in the `taskChanges` subscription. The answers:

| Status | Meaning |
|---|---|
| 201 | every event is in the log |
| 400 | not JSON, a wrong content type, `specversion` other than `1.0`, an event or actor the machine does not declare, a machine the server does not draw, an entry keyed by neither or both of `subject` and `run`, a bad `time`, or `data` that is not an object |
| 401 | a missing or unknown token |
| 403 | a `source`, `machine` or `actor` the producer is not declared for |
| 413 | `data` over 8 KiB, or a body over the ingest's size limit |
| 503 | the event log did not take an entry; every entry has a stable id, so post the batch again |

### Over Connect

The same ingest is served on the same port over Connect (gRPC-compatible on a direct HTTP/2 connection; a proxy that
speaks HTTP/1.1 to the server carries only the Connect protocol, so a client behind one uses Connect): service `starpulse.v1.CloudEventsIngest`, methods `Publish`
(one `io.cloudevents.v1.CloudEvent`) and `PublishBatch` (a `CloudEventBatch` of up to 200), both answering
`google.protobuf.Empty`. The token is the `authorization` metadata, `Bearer <token>`. Attributes are the table above's,
carried in the event's `attributes` map (`time` as `ce_timestamp` or an RFC 3339 `ce_string`); `data` is JSON text or
bytes, never a protobuf `Any`. The checks and the all-or-nothing batch are the ingest's; on the gRPC wire
`grpc-status` arrives in the HTTP/2 trailers. A refusal's HTTP status maps to a code:

| HTTP | Connect and gRPC |
|---|---|
| 400 | `INVALID_ARGUMENT` |
| 401 | `UNAUTHENTICATED` |
| 403 | `PERMISSION_DENIED` |
| 413 | `RESOURCE_EXHAUSTED` |
| 503 | `UNAVAILABLE` |

## GitHub Actions

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
start_url = "https://github.com/trantor-org/starpulse/actions"   # the page's Run in GitHub ↗ link
```

- **Adapter worker.** `serve` starts it as a child for each instance that names this adapter (`starpulse worker github-actions --config <this file>`). It
  beats into the event log, and with the worker down or never started the page shows the instance with the error "the
  `<name>` worker has not reported" or "last reported Ns ago" (a beat older than 60 s).
- **Credentials** come from the environment: `GITHUB_TOKEN` or `GH_TOKEN` (read and `actions: write` on the repository),
  and `GITHUB_API_URL` for GitHub Enterprise Server. Without a token the repository is still read, at GitHub's lower
  unauthenticated rate limit, and nothing starts.
- **Starting.** StarPulse starts nothing: the page's `Run in GitHub ↗` link opens `start_url`, and a run is started there.
- **Events.** The repository is read every 60 s: the workflow list and the repository's latest runs, two calls however
  many workflows it has, and a workflow again only when it is new, its file or latest run changed, or its latest run has
  not ended (its jobs move without the run moving). A quiet repository costs about 120 calls an hour. A `workflow_run`
  the adapter does not receive webhooks itself, so a deployment with no relay GitHub can reach shows a run within the 60 s.

## systemd timers

`type = "systemd"` reads a declared allowlist of a host's timers, not every timer on it. Each timer is a workflow named
for its stem (`apt-daily`) with one step, the service it activates (`apt-daily.service`), and that service's latest run.

```toml
[[runs]]
name = "timers"
type = "systemd"
url = "systemd-tmpfiles-clean, apt-daily.timer, user/claude-sessions-snapshot"
```

- **Adapter worker.** `serve` starts it as a child for each instance that names this adapter (`starpulse worker systemd
  --config <this file>`), on the host whose timers it reads. The page shows an instance whose worker never reported or
  stopped, as for the other adapter workers.
- **`url` is the allowlist:** comma-separated timer units. A bare name reads the system manager and a `user/` prefix
  reads `systemctl --user`; a name without `.timer` means `<name>.timer`. Two timers with one stem are refused.
- **Status** comes from the service's `systemctl show`: an `ActiveState` of `activating`, `active`, `reloading` or
  `deactivating` is `running`; otherwise a `Result` other than `success` is `failed`, and `success` is `succeeded`, or
  `not_started` when the service has never started. The engine's own state stays in `raw` as `<ActiveState>/<Result>`.
  The run starts at `ExecMainStartTimestamp` and ends at `ExecMainExitTimestamp`.
- **Errors.** An allowlisted unit that does not exist, or a `systemctl` that fails or answers a timestamp not in UTC,
  shows as the instance's error and keeps the last reading; no timer is dropped silently.
- **Events.** The allowlist is read once at start. After that a `gdbus monitor` per manager (system, and user when an
  entry has `user/`) streams the D-Bus `PropertiesChanged` signals of the units, and a change to a timer or its service
  re-reads only that timer, a third of a second after the signals settle. A monitor that exits is started again and its
  timers are read again; a `runs:resync` entry naming the instance reads them all again. Idle, the adapter starts no
  `systemctl`. systemd sends those signals only while a client holds `Manager.Subscribe` and `gdbus monitor` never
  subscribes (the system manager has other subscribers, the user manager none), so each monitor also holds that
  subscription on a socket of its own for as long as it runs. Each `gdbus` child ends with the stream that reads it
  (terminated when the stream closes, SIGTERM from the kernel when its parent thread dies), so a restart leaves none
  behind. The adapter reads no event-log entries. It starts nothing: starting a root unit needs a polkit grant,
  and a timer has no runner page, so `start_url` stays unset. `systemctl` and `gdbus` (`libglib2.0-bin`) must run on the host that serves StarPulse.

## Temporal workflows

`type = "temporal"` reads the Temporal server that runs the engine's own workflows and shows them beside the scheduler's
DAGs. `url` is the Temporal UI server (`http://host:8233`); its HTTP API lists the default namespace. Each of the four
workflow types `task_lifecycle`, `task_phases`, `AlertInvestigationWorkflow` and `CommandWorkflow` is a workflow, shown even with no run.

```toml
[[runs]]
name = "temporal"
type = "temporal"
url = "http://temporal.internal:8233"
```

- **Active runs.** Every running execution is an active run with the Board task its workflow id names (`TASK-N`; an
  alert has none), the activity it is on, that activity's attempt and the message its last attempt failed with.
- **Recent runs.** The last day's closed executions, the newest 100 closed and the newest 100 failed, each with its Temporal
  status. A failed one carries the activity it failed on, that activity's attempt and the failure message, read from its
  history once, since a closed execution never changes.
- **Graph.** Each workflow draws the steps of its oldest running execution, else of its newest closed one, from that
  execution's history (events up to 500). The mapping is below. A history the adapter cannot draw (the server will not
  give it, a second page of events, more than 60 nodes, an event it cannot read) leaves the workflow with no graph, and the
  page lists its runs as before.
- **Polling.** The server pushes no change, so the adapter lists it every 15 s: three listings, and one describe for each
  running execution, plus one history read for each workflow's drawn execution (a closed one is read once). A server it cannot reach shows as the instance's error, with the last reading kept.
- **Adapter worker.** `serve` starts it as a child for each instance that names this adapter (`starpulse worker
  temporal --config <this file>`). These workflows start from the Board's lifecycle and from the Temporal UI that `start_url` names.

### Temporal graph mapping

| Temporal | Drawn as |
| --- | --- |
| Activity (`ACTIVITY_TASK_SCHEDULED`) | A node named for the activity type; a `run_command_step` activity is named for the `id` of the command step it runs. A name that repeats becomes `name #2`. |
| Child workflow (`START_CHILD_WORKFLOW_EXECUTION_INITIATED`) | A node named for the child's workflow type. |
| Node state | Scheduled only is `queued`; started is `running`; completed is `succeeded`; failed or timed out (an activity, a child, or a child that failed to start) is `failed`; canceled or terminated is `aborted`. |
| Retry | Not a node: the attempt number is the node's `raw` (`attempt 3`) once above 1. |
| Order | A node waits on the nodes that had closed when it was scheduled, less the ones another waited-on node already follows. Nodes scheduled together, such as a fan-out, are parallel. |
| Timer, signal, marker, search-attribute update, workflow task | Not nodes. A wait or signal only separates nodes in time. |

What does not map cleanly:

- An edge is the order the workflow scheduled work in, not a dependency it declared. A step the engine held back for a
  concurrency limit looks like it waits on the step that freed the slot, and a fan-out of unrelated steps scheduled
  one after another looks like a chain.
- Only work that has been scheduled is drawn: a step still to come, or skipped because its dependency failed, is absent.
- A loop (`AlertInvestigationWorkflow` repeating `dispatch_step`) draws one node per pass as a chain; a long-running
  workflow that waits on signals (`task_lifecycle`, `task_phases`) draws what has run so far, and past 60 nodes or one
  page of events is listed, not drawn. Such a workflow is always a finite DAG of its history, so none needs another view.
- The active run's `steps` (the pending activities) keep their activity names, so a `run_command_step` node takes its
  state from the graph, not from the run.

## Woodpecker pipelines

`type = "woodpecker"` reads a Woodpecker CI server and shows each repository's pipelines beside the scheduler's DAGs.
`url` is the server and the repository, `http://host:8004/owner/name`. Each pipeline event (`pull_request`, `push`,
`cron`, `manual`, and any other the server reports) is a workflow named for the event, shown even with no run.

```toml
[[runs]]
name = "woodpecker"
type = "woodpecker"
url = "http://ci.internal:8004/acme/app"
```

- **Token.** The adapter reads `WOODPECKER_TOKEN` from its environment and sends it only as an `Authorization: Bearer`
  header on its own requests. A page receives the run records, never the token.
- **Active runs.** A running or pending pipeline is an active run, with the step it is on, the task its branch or title
  names (`TASK-N`), its pull request, its commit and a link to its page on the server.
- **Recent runs.** The newest 60 pipelines of the repository, closed ones of any status. A failed one carries the step it
  failed on and its exit code, read once, since a closed pipeline never changes. A pipeline the server never ran (status
  `error`, no `workflows`) is a failed run with no steps and no failure line.
- **Graph.** Each event's workflow draws the steps of its oldest running pipeline, else of its newest closed one. The
  mapping is below. A detail or config the adapter cannot read or draw leaves the workflow with no graph, and the page
  lists its pipelines as before.
- **Reading.** The server pushes no change, so the adapter lists it once at start and again for each `runs:resync` entry
  naming the instance (a commit status Woodpecker posts writes one): one listing, and one detail read for each
  running pipeline and for the drawn one (a closed pipeline's detail is read once; a pipeline with more than one workflow
  also reads its config once, for the workflows' `depends_on`). A server it cannot reach shows as the instance's error, with the last reading kept, and the other
  instances keep drawing.
- **Adapter worker.** `serve` starts it as a child for each instance that names this adapter (`starpulse worker
  woodpecker --config <this file>`). It is read-only: nothing triggers, cancels or retries a
  pipeline.

### Woodpecker graph mapping

| Woodpecker | Drawn as |
| --- | --- |
| Workflow | A node named for the workflow, in the workflow's state. It waits on the workflows its file's top-level `depends_on` names (read from `/pipelines/N/config`). |
| Step | A node named `workflow / step`, so the page folds it under its workflow. The failure line and a running pipeline's `steps` use the same names. |
| Step `depends_on` | Edges to the named steps of the same workflow. |
| Step with no `depends_on` | Waits on the workflow's clone step (or the workflow, with none) when a sibling declares `depends_on`; otherwise the steps chain in the order they run after the workflow. |
| Clone step | A step that waits on the workflow; later steps wait on it. |
| Step state | `success` is `succeeded`; `failure` and `error` are `failed`; `pending` and `blocked` are `queued`; `killed`, `canceled` and `declined` are `aborted`; `skipped` is `skipped`. |
| Service (`type: service`) | Not drawn: a background container is no step of the order. |

What does not map cleanly:

- A workflow whose steps all declare `depends_on: []` runs in parallel but draws as a chain, because the server reports
  an empty list the same way as none.
- A step skipped by a `when` rule draws as `skipped`, and a workflow the file's `when` left out of the pipeline is absent;
  the server reports neither the rule nor the branch.
- A matrix workflow reports one workflow per cell; the graph draws each as its own workflow, and a `depends_on` on the
  file applies to the cell names the server reports, which the config read cannot match when the names differ.
- A pipeline with `errors` and no workflows has no graph.

## Show pull requests and their checks

Pull request events reach the event log through the App webhook: point the App's webhook at the listener described in
[Save GitHub webhook deliveries](#save-github-webhook-deliveries). The webhook is the normal delivery path. With
`reconcile_token_env` set, the sweeper also reads GitHub and creates an inbox row for a closed pull request that no
delivery reported ([Reconcile the inbox against GitHub](#reconcile-the-inbox-against-github)).

- **`github-pull-request` machine.** `PR_OPENED`, then `CHECKS_PASSED` or `CHECKS_FAILED` once every check run on the
  head commit has completed, then `PR_MERGED` or `PR_CLOSED`.
- **Keys.** Link the pull request's URL to the task as a reference. The consumer selects the unarchived task whose
  references hold that URL and keys the event by it; a branch name alone is not enough. With no task linked it retries,
  then skips the delivery as `no-task`.
- **Deliveries** are verified with the App's webhook secret (`secret_env`). A redelivery appends nothing already in
  the log.

The two machine definitions ship in the package under `starpulse/machines/`.
