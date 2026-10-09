# Connect sources

Each source moves tasks or runs through a machine on the page: agent sessions, scheduler runs, pull requests.

## Show your Claude Code sessions

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

## Measure session and slice health

The same receiver also reads each export of Claude Code and of Codex for what a session did, and the server serves it as
`GET /api/analytics/sessions[?hours=N]` (168 hours by default). Point Codex's log export at it in its `config.toml`:

```toml
[otel]
log_user_prompt = false
exporter = { otlp-http = { endpoint = "http://127.0.0.1:4319/v1/logs", protocol = "json" } }
```

A session is one harness session id; it has one row per task it worked, found from the branch the export names
(`vcs.ref.head.name`, which Codex's export does not carry, so its sessions have no task until a shell `git switch` or
`git checkout` in them names one). The body is `{now, window_s, sessions, slices}`:

- A `sessions` row is `{harness, session, task, kind, first_at, last_at, prompts, operator_prompts, requests,
  side_requests, tool_calls, tool_failures, tools, rejections, skills, compactions, interrupts, models, efforts,
  model_changes, effort_changes, tokens, cost_usd, agent_s, operator_wait_s, idle_s}`. `kind` is `headless`,
  `interactive` or `unknown`. `operator_prompts` are the human prompts after the first; `requests` are the main
  thread's model calls and `side_requests` a subagent's. `rejections` counts rejected tool decisions by their source
  and `compactions` by trigger. `tokens` is `{input, output, cache_read, cache_write, reasoning}`, with Codex's cached
  tokens taken out of its input; `cost_usd` is null for a session whose harness exports no cost.
- A `slices` entry adds up the sessions that worked one task: `sessions`, `steps`, `operator_prompts`, `interrupts`,
  `interventions` (operator prompts plus interrupts), `escalated` (a model or effort changed between main-thread
  requests) and `clean` (one session, no intervention, not escalated), with the same tokens, cost and time sums.
  Whether the task then settled in Review or Done is the board's fact, which the reader joins.
- Time is the gap between a session's consecutive signals, `operator_wait_s` where a human prompt ends it, `idle_s`
  where it is longer than ten minutes, and `agent_s` otherwise. An export marks no turn end and no pending background
  task, so a wait for one is `agent_s` up to ten minutes.

What an export cannot say is absent rather than guessed: Claude Code exports no user interrupt, Codex exports an
interrupted turn only in `codex.turn_cost`, which it sends only with an API key, and Codex has no compaction event.
Signals are kept in the event log's `telemetry:signals` stream, pruned by `event_log_retention_days` like any row, so a
window longer than the retention reads only what remains. A server with no such stream is 501, a window that is no
positive number 400.

## Report runs from any scheduler

```sh
starpulse emit start --workflow nightly --run 2026-10-03 --status running
starpulse emit end   --workflow nightly --run 2026-10-03 --status succeeded --step load --depends fetch
```

A workflow no adapter lists is drawn from the step graph its `emit` calls add up to, and that graph is kept in
the history store across restarts.

A producer on another host, or an engine that can only send webhooks (Cronicle, Rundeck, a GitHub `workflow_run`
relay), posts the same event to the server instead. Name an environment variable for the instance's token in the
config (`token_env`, in [the config file](serving.md#config-file)), set it where `serve` runs, and send the token as a bearer:

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
run_safe = ["ui-preview.yml"]
```

- **Credentials** come from the environment: `GITHUB_TOKEN` or `GH_TOKEN` (read and `actions: write` on the repository),
  and `GITHUB_API_URL` for GitHub Enterprise Server. Without a token the repository is still read, at GitHub's lower
  unauthenticated rate limit, and nothing starts.
- **Run now** dispatches the workflow on the default branch (`workflow_dispatch`) and answers its run id. It is drawn
  only on a `run_safe` workflow whose file declares `workflow_dispatch`; any other workflow is refused.
- **Events.** The repository is listed every 60 s. A `workflow_run` webhook, mapped with
  `starpulse._internal.runs.github_actions.workflow_run_entry` and sent to the ingest (or `starpulse emit`), reads that workflow again
  at once.

## systemd timers

`type = "systemd"` reads a declared allowlist of a host's timers, not every timer on it. Each timer is a workflow named
for its stem (`apt-daily`) with one step, the service it activates (`apt-daily.service`), and that service's latest run.

```toml
[[runs]]
name = "timers"
type = "systemd"
url = "systemd-tmpfiles-clean, apt-daily.timer, user/claude-sessions-snapshot"
```

- **`url` is the allowlist:** comma-separated timer units. A bare name reads the system manager and a `user/` prefix
  reads `systemctl --user`; a name without `.timer` means `<name>.timer`. Two timers with one stem are refused.
- **Status** comes from the service's `systemctl show`: an `ActiveState` of `activating`, `active`, `reloading` or
  `deactivating` is `running`; otherwise a `Result` other than `success` is `failed`, and `success` is `succeeded`, or
  `not_started` when the service has never started. The engine's own state stays in `raw` as `<ActiveState>/<Result>`.
  The run starts at `ExecMainStartTimestamp` and ends at `ExecMainExitTimestamp`.
- **Errors.** An allowlisted unit that does not exist, or a `systemctl` that fails or answers a timestamp not in UTC,
  shows as the instance's error and keeps the last reading; no timer is dropped silently.
- **Events.** The allowlist is read every 30 s; the adapter reads no event-log entries. There is no Run now: starting a
  root unit needs a polkit grant, so the adapter offers no start. `systemctl` must run on the host that serves StarPulse.

## Show pull requests and Copilot work

`python -m starpulse._internal.pulls.github` reads a repository's 30 most recently updated pull requests every `--interval` seconds
(300 by default) and appends their events to the event log, beside the server:

```sh
uvx --from starpulse python -m starpulse._internal.pulls.github --repo trantor-org/starpulse
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
