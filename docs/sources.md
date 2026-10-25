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
reply and tool text is never stored.

## Measure session and slice health

The same receiver also reads each export of Claude Code and of Codex for what a session did, and the server serves it as
`GET /api/analytics/sessions[?hours=N]` (168 hours by default). Point Codex's log export at it in its `config.toml`:

```toml
[otel]
log_user_prompt = false
exporter = { otlp-http = { endpoint = "http://127.0.0.1:4319/v1/logs", protocol = "json" } }
```

Cursor exports no telemetry, so a one-shot reader takes its agent transcripts instead, and a scheduler runs it:

```sh
python -m starpulse.cursor [--root ~/.cursor/projects] [--hours 48] [--config FILE] [--redactor MODULE:FUNCTION]
```

It reads each `<project>/agent-transcripts/<conversation-id>/<conversation-id>.jsonl` written in the window into the same
signals, under harness `cursor`; a transcript read again adds nothing. A transcript records no model, effort, token, tool
result or per-line time, so a Cursor row has `main_model` null, zero tokens, and `agent_s`, `idle_s` and
`operator_wait_s` of 0 (every signal takes the time of the last prompt, to the minute). It carries steps (`requests`),
tool calls by name (each `ok`), prompts (`human` with a `<user_query>`, otherwise `injected`), task claims and `git
switch` from `Shell` commands, `turn_ended` errors as `interrupts`, and one compaction per `compaction/segment_*.md`
(trigger `unknown`). Subagent transcripts are not read. No Cursor row is in any ranking.

A transcript carries no token count either, and Cursor has no client-side compaction threshold, so a second one-shot
holds each Cursor task session to a context limit from outside, and a scheduler runs it every few minutes:

```sh
python -m starpulse.cursor_context [--config FILE]
```

For each tmux session `task-N` whose pane runs `cursor-agent` it reads the footer percent of the pane (`Auto  60.3%`)
against `window_tokens` and appends `{session, task, tokens, window}` to the `cursor:context` stream, one row per session
per minute. A session at or past `limit_tokens` is asked once to update its working doc, comment on its task and
commit its work in progress. On a later run it is ended and started fresh on the same task through
`session_start_url` when its pane stopped changing, or `wrapup_s` seconds after the ask. A pane with no footer percent,
a session below the limit and a non-Cursor session are left alone. The limits are the config's `[cursor_context]`
table ([Config file](serving.md#config-file)).

A session is one harness session id; it has one row per task it worked, found from the branch the export names
(`vcs.ref.head.name`, which Codex's export does not carry, so its sessions have no task until a shell `git switch` or
`git checkout` in them names one), or a command or `Skill` call that matches an `[analytics]` `claims` pattern claims
one. Every step after a claim belongs to the claimed task, until the next claim or switch, and the steps before a
session's first claim or task-naming switch, when its launch branch names no task, belong to that first task. The body is
`{now, window_s, sessions, slices}`:

- A `sessions` row is `{harness, session, task, kind, first_at, last_at, prompts, operator_prompts, prompt_labels, requests,
  side_requests, tool_calls, tool_failures, tools, rejections, user_rejects, gates, skills, compactions, interrupts, models, efforts,
  main_model, main_effort, model_changes, effort_changes, tokens, cost_usd, agent_s, operator_wait_s, idle_s, steps_before_edit, complete}`.
  `models` and `efforts` list every value seen, side requests included; `main_model` and `main_effort` are the first
  ones the main thread reported (null until it reports one), the session's profile.
  `kind` is `headless`, `interactive` or `unknown`. `operator_prompts` are the human prompts after the task's claim
  (after the session's first prompt for the task it launched on or first claimed), and `prompt_labels` counts those the
  instance's labeller named by intent (none when no labeller is configured; it changes no other count); `requests` are the main thread's model calls and
  `side_requests` a subagent's. `steps_before_edit` is the model requests before the task's first successful `Edit`,
  `Write`, `MultiEdit` or `NotebookEdit` or shell command that writes a file (an output redirect to a path, a pipe to `tee`,
  `sed -i`, `patch`, `git apply`, or an interpreter fed a heredoc, whose body is elided, so a read-only script counts), null until it has one. `complete` is true for a session that loaded the
  `completion_skill` and then ran a shell command matching `completion_call`. `rejections` counts rejected tool decisions by their source and `user_rejects` those whose source is `user_reject` or
  `user_abort`,
  `gates` the same rejections by `<source>:<tool>` (`hook:Bash`, `user:Edit`; the export names no hook script, so a
  hook's gate is the tool it refused), and `compactions` by trigger. `tokens` is `{input, output, cache_read, cache_write, reasoning}`, with Codex's cached
  tokens taken out of its input; `cost_usd` is null for a session whose harness exports no cost.
- A `slices` entry adds up the sessions that worked one task: `sessions`, `steps`, `operator_prompts`, `prompt_labels`, `interrupts`,
  `rejections`, `user_rejects`, `interventions` (operator prompts plus interrupts), `raises` and `lowers` (sessions that moved up or down the
  step-down ladder mid-task), `escalated` (a model or effort changed between main-thread requests) and `clean` (one session, no intervention, not escalated), with the same tokens, cost and time sums, and
  `complete` and `steps_before_edit` of its sessions (the earliest that has one).
  Whether the task then settled in Review or Done is the board's fact, which the reader joins.
- A turn is the signals that share a Claude Code `prompt.id`; its end is its last signal. A prompt is labelled
  `injected` when its opening matches an `injected_openings` prefix and `human` otherwise; the label is kept and the
  prompt's text never is. With an `[analytics.labeller]` configured, a `human` Claude Code prompt's text is also sent
  to that typed-decision endpoint, which names its intent (one of the table's `criteria`, else `unsure`); that
  label is kept on the prompt and the text never is. An endpoint that is unreachable, slower than its `timeout`
  (default 2 s) or answers nothing usable leaves the label empty and ingest goes on. Codex exports no `prompt.id`, so a Codex prompt's turn is the signals up to the next
  prompt, and its prompts are all `human`.
- Time comes from the events' own durations, not from the gaps between them. `agent_s` is the sum of the model
  requests' and tool results' durations (a subagent's included) and of the `hook_execution_complete` events a turn
  caused (their `total_duration_ms`; a hook with no `prompt.id`, such as a session-start one, is no agent time). A
  tool result's duration leaves its pre- and post-tool hooks out, so the hook events are what carry that time. Claude
  Code logs no permission-prompt duration: only its `claude_code.tool.blocked_on_user` trace span has one, and traces
  are not read. `operator_wait_s` is the time from the end of the turn
  before to a human prompt (never the session's first), `idle_s` the same before an injected prompt, a wait for a
  background task or scheduler. A prompt typed while the turn before still worked waits for nothing. A result of an
  `operator_tools` tool (a question answered, a plan approved) is no prompt but charges the silence before it to
  `operator_wait_s`: from the last signal before it, other than that tool's own decision, to the tool's start. Codex exports no
  request duration, so its `agent_s` is its tool results' alone.
- An `interrupt` is a Claude Code turn with a `prompt.id` and no closing reply: a turn still running counts until its
  reply lands. Codex has no reply signal, so only the interrupts it exports count for it.

What an export cannot say is absent rather than guessed: Claude Code exports no user interrupt, so one is read from
a turn that never replied, Codex exports an interrupted turn only in `codex.turn_cost`, which it sends only with an API
key, and Codex has no compaction event.
Signals are kept in the event log's `telemetry:signals` stream, a private stream that is no contract and changes
without notice, pruned by `event_log_retention_days` like any row, so a window longer than the retention reads only
what remains. A server with no such stream is 501, a window that is no
positive number 400.

One signal is one step of the record the steps-per-clean-completion ledger counts: a `request` is one model call, with
its model, effort, duration and the four token counts, and a `compaction` names its trigger. Two fields say whose step
it was and whether to count it, and a third holds a command:

- `agent`: the subagent that made a `request` or `tool` step, from the export's `agent.name` or, for Claude Code, its
  `query_source` when that names a subagent; Codex's `agent_name` on a tool result. Empty for the main thread. A
  subagent's steps carry the parent's session id, so they count toward the task that spawned it.
- `captured`: false for every Codex signal, which the ledger does not cover yet, so a ranking leaves it out. A signal
  stored before the field existed reads as captured only when its harness is Claude Code.
- `command`: a Claude Code shell result's command, empty otherwise. It is kept only when the adapter runs with
  `--redactor MODULE:FUNCTION`: the function filters the text, a heredoc body is replaced by
  `[heredoc length=<bytes> sha256=<hex>]` before the function sees it, and a function that raises keeps no command. No
  exit status is stored, because the export carries none; `ok` is the result's `success` and `seconds` its duration.

## Read each step of a session

`GET /api/analytics/steps[?hours=N]` (168 hours by default) lists every model request of the window, oldest first, so a
reader can charge tokens to the skill in force and the work done. The body is `{now, window_s, steps}`; a step is
`{harness, session, task, at, model, origin, skill, activities, keys, tokens, captured}`, counts and names only:

- `task` is the one the session's rows name for that request; `origin` is `main`, `side` (a subagent) or `auxiliary`.
  For Claude Code a request's `query_source` of `""`, `sdk`, `repl_main_thread` or `repl_main_thread:` plus any suffix
  (`repl_main_thread:outputStyle:custom`, which the main thread carries under a custom output style) is `main`;
  `compact` is `auxiliary`; every other source stays `side`.
- `activities` and `keys` hold one entry per tool call the step made, in order: the activities the call performed (as
  under [Find missed skill loads](#find-missed-skill-loads-and-recurring-work)) and its key, the shell command the
  `--redactor` left, else the tool's name. A command is therefore present only after the configured filter.
- `skill` is the skill most recently loaded in the session, counting a load the step itself made, and `none` before
  any load. A session that began before the window reads `none` until its first load inside it.
- `tokens` is `{input, output, cache_read, cache_write, reasoning}`; `captured` is false for every Codex step.

The export's order cannot say which request issued a call, because Claude Code logs a request when its stream ends and
starts a tool before then. A call belongs to the latest request that started (its time less its duration) at or before
the call started, and one that started before every request of the window belongs to the first, so steps of
subagents that overlap can take each other's calls. A server with no telemetry stream is 501 and a window that is no
positive number 400. `starpulse analytics steps [--hours]` reads it.

## Price each transition and report each cell

`GET /api/analytics/transitions[?hours=N]` and `GET /api/analytics/cells[?hours=N]` (168 hours by default) fold the same
steps by the kind and size of the task they worked, which the board's `kind-<kind>` and `size-<n>` labels give. A
task missing either label is in neither report, a Codex step (`captured` false) is in neither, and a window that is no
positive number is 400, one longer than the telemetry history 400 with `history_s`, a server with no telemetry log 501
and one that cannot read it 503, as for steps. `starpulse analytics transitions|cells [--hours]` read them.

`transitions` is `{now, window_s, transitions}`, one row per kind, size and skill in force (the transition), by that
order. Its columns:

- `kind`, `size`, `skill`: the cell and the skill in force on the steps, `none` before any load.
- `tasks`, `steps`: the tasks the row's steps worked and the model requests among them. A subagent's requests carry
  its parent's session, so they count toward the task that spawned it; `side_steps` is their share. A compaction's own
  call is no step.
- `wasted_steps`, `wasted_rate`: steps with a call that failed, was refused by a guard or hook, or repeats the shell
  command of the call before it in the session, and their share of `steps`. A refusal names only its source (hook
  gate names are not exported), and a call with no stored command (the adapter ran with no `--redactor`) cannot repeat.
- `agent_s`: the seconds of the steps' requests and tool calls, hooks not included.
- `peak_context`: the most input, cache-read and cache-write tokens one request held.

Blind spot: a skill is in force from its load to the next, so a stretch no skill governs is charged to the skill
before it, and the transition is the skill, not a machine edge.

`cells` is `{now, window_s, cells}`: the median agent steps per clean completion of each kind and size, by kind then
size. A completion is a task slice that loaded the completion skill and ran the completion call (`complete` under
session health), and it is *clean* when one session did it with no operator prompt, interrupt or model or effort
change. A cell with fewer than 5 clean completions is not listed. The medians are over its `holdout`, the latest fifth
of the clean completions by the end of their last session, rounded up, so a median is never read from the tasks a
change was tuned on. Its columns:

- `kind`, `size`; `n` clean completions and `completions` of any kind; `clean_rate`, their ratio.
- `median_steps`: main and subagent requests of the holdout's tasks.
- `median_operator_prompts`: human prompts after the task's claim, the steering count. A clean completion has none, so it
  is the median over the latest fifth (rounded up) of all the cell's completions, clean or not.
- `median_steps_before_edit`: model requests before the task's first successful file write, by an edit tool or a shell
  command that writes a file; null when no holdout task made one.

Blind spot: a cell can improve because its tasks got easier, so read `n`, `clean_rate` and the two medians beside
`median_steps`. A cell with a few tasks has a median of one or two.

## Graph a transition's activities and diff a fast run against a slow one

`GET /api/analytics/graph`, `/stages` and `/diff` (`?hours=N`, 168 by default) read the same steps by the kind and size
of the task they worked, with the refusals and exclusions of the transition and cell reports: a task missing its
`kind-<kind>` or `size-<n>` label and a Codex step are in none. A *run* is one task's steps under one skill in force,
and its activities are those the main thread's steps made in order, less the `[analytics]` `stop_activities`; a
subagent's steps run beside the main thread, so they add edges that never happened and are left out of the activities
(they count in a run's steps). `starpulse analytics graph|stages|diff [--hours]` read them.

`graph` is `{now, window_s, graph}`, one row per edge, by kind, size, skill, source, then target:

- `kind`, `size`, `skill`: the transition.
- `source`, `target`: two activities, the second directly after the first in a run; `[start]` and `[end]` bound a run.
- `runs`, `count`, `share`: the tasks the edge occurred in, its occurrences and their share of those that leave `source`.
- `cut`: `source` is a *judgement cut*. An activity is one when at least 5 runs went through it and its commonest
  successor takes no more than 80% of the occurrences that leave it: the agent chose there. Every edge leaving a cut
  is marked; an activity with one way on is a deterministic stretch.

Blind spot: a cut is a place where runs differ, not proof that the difference needed judgement; a branch on a failed
test and one on a taste are both cuts. An activity is the closed vocabulary of a tool call, with no arguments, so two
runs of `make test` on different targets are one edge.

`stages` is `{now, window_s, stages}`. A stretch no machine models is a run under no skill (`none`), and one of at
least 20 activities is *long*. A kind x size cell with at least 5 long runs is split at its judgement cuts (the graph's,
over the long runs only): a stage ends with the cut that closes it and the next stage opens with that cut, the first
with `[start]`. One row per kind, size and stage, by that order:

- `stage`: the activity that opens the stage, `[start]` for the first.
- `runs`, `median_activities`: the tasks the stage occurred in over the window and the median activities it held; 0
  and null when it did not occur.
- `previous_runs`, `previous_median_activities`: the same over the `hours` before the window.
- `stability`: of the cell, the stages in both windows over the stages in either, 1 when the cuts did not move; null
  when a window mined none. A stage with `runs` 0 or `previous_runs` 0 is one that appeared or went.

The history must hold twice `hours`, else the read is 400 with `history_s`. No machine edge is added from a stage: it
is a name for a stretch of one window's runs and can move with the mining, which `stability` is there to show.

`diff` is `{now, window_s, diff}`, one row per transition of a kind and size, by that order, with the skill `none`
left out. Its group is the transition's runs of tasks that completed clean (`cells`). A group under 5 reports
nothing. Its columns:

- `runs`, `conformant`: the group's size and how many of its runs conform to the skill's machine.
- `reference`: `{task, steps}` of the conformant run with the fewest steps (a subagent's included).
- `slow`: `{task, steps}` of the run with the most steps, conformant or not.
- `slow_only`, `reference_only`: `{activity, count}` of what the slow run made more often than the reference and the
  reverse, by count then activity.

A run *conforms* when its tool calls, oldest first, reach in order the stages of its skill's
`[[analytics.skill_machines]]` entry ([Config file](serving.md#config-file)); a skill with no entry has every run
conform. The reference is therefore never a run that skipped a stage, such as RED, however few steps it took, and a
transition whose clean group has no conforming run is listed with `conformant` 0, `reference` null and
`reference_only` empty, so the skipped stage shows.

Blind spot: the diff compares activity counts of two runs, not their order, and one reference is one run's way, not
the best way. The stages an instance declares are its reading of the skill's steps; StarPulse does not derive them.

## Read the steps still to come from each state of a skill machine

`GET /api/analytics/cost-to-go` (`?hours=N`, 168 by default) is `{now, window_s, cost_to_go}`, one row per state of
each `[[analytics.skill_machines]]` machine within a kind and size, by kind, size, skill, then the machine's order with
`[start]` first. A step is in the stage its run had reached when the step began, and `[start]` before the first stage.
The rows come from the trajectories' absorbing chain over the clean completed runs of the skill (the `diff` report's
runs), with the run's last step absorbing into its end; a state's `cost_to_go` is the expected agent steps from a run's
first step in it until the run ends, and the unit is steps, not days. A skill with no machine has no rows.

- `kind`, `size`, `skill`, `state`: the cell.
- `n`: the times the state was seen left in those runs. Every state is listed whatever its `n`; a consumer holds a cell
  with a small one (a gate on cost holds a cell under 5).
- `cost_to_go`: the expected steps, as the closed form `(I - Q)^-1` of the observed transitions.

Blind spot: a state reached once reads as certain. The chain is the observed transitions only, with no smoothing, so
`n` is the confidence a reader must apply.

## Find missed skill loads and recurring work

The same signals say what each session did, not only how long it took. A tool call is lifted to *activities* with no
argument, so work recurs across sessions: a non-shell tool is its bare name; a shell call is each statement's leading
command, as `git status`, `gh pr view`, `make test`, `bin/<script>`, `ssh <user@host>`, `shell_read`, `shell_search`,
its binary name or `shell_other`. An export that carries no command (`OTEL_LOG_TOOL_DETAILS` off) leaves a shell call
as its tool name. Claude Code caps each `tool_input` string over 512 characters, so a shell call reads its command from
`tool_parameters.full_command`, which is whole, and falls back to `tool_input`. `uv run` is unwrapped through its flags,
including the directory after `--project` or `--directory`. The path a file tool read or wrote is kept raw and cut at read time to an *area*, its first two
components below an `[analytics]` root. A *case* is one session's work on one task, as under session health; a session
that no branch or claim ever ties to a task is a case with no task.

`GET /api/analytics/missed-loads[?hours=N&skill=NAME&list=N]` reports, per skill declared in `[analytics]`, the cases
of the window (168 hours by default; a window longer than the telemetry history is 400 with `history_s`, as on every telemetry route) that ran its trigger and those of them that did so without activating it. The body
is `{now, window_s, skills}`; a `skills` entry is `{skill, performed, missed, listed}`, `listed` the `list` (5 by
default, 0 or more) most recent missed cases as `{harness, session, task, last_at}`. A case performs a trigger by an
activity matching one of its globs, or, with tool calls, a task title matching its `title` or carrying its `label`
(from the board's open and settled tasks).

`GET /api/analytics/trace-clusters[?hours=N&threshold=D&min_sessions=N&outliers=N&new_hours=N]` groups the window's
cases that made a tool call by what they did. Each case is a set of its activities (not a `stop_activities` one) and
areas, weighted TF-IDF (a feature in under `5` cases or in over a tenth of them says nothing) and normalized; cases
merge by average-linkage on cosine distance while the nearest pair is under `threshold` (0.8 by default, up to 2). A
cluster keeps only if it has `min_sessions` (5 by default, 1 or more) distinct sessions. `new_hours` keeps only the
clusters whose oldest case is that recent; clustering still runs over the whole window. The body is `{now, window_s,
threshold, min_sessions, cases, clustered, clusters}`, and a cluster is:

- `key`: the first 12 hex digits of the SHA-1 of its sorted `descriptors`, so it holds while those hold.
- `descriptors`: its six heaviest features, as `a:<activity>`, `r:<area>` or `w:<area>`.
- `sessions`, `cases`, `tasks`, `first_at`, `last_at`, `kinds` (cases by `headless`, `interactive`, `unknown`),
  `sample_sessions`, `sample_tasks` (5 each) and the three `titles` most of its cases carry.
- `skills`: the three skills its cases activated most, as `{skill, cases}`, without `lifecycle_skills`; `uncovered`
  counts the cases that activated none of them.
- `missed_loads`: the declared skills whose trigger some of its cases ran without activating, as `{skill, performed,
  missed}`.
- With `outliers=N`, `medoid` and the `N` furthest `outliers`; otherwise `medoid` is null and `outliers` is empty. The
  medoid is `{case, median_distance, trace}`: the case with the least total normalized edit distance to the others over
  its activity order, the median of its distances to them, and its trace (`stop_activities` dropped, adjacent repeats
  collapsed). An outlier is `{case, distance, deletions, insertions}`: its distance from the medoid, the medoid's
  activities it lacks and its own that the medoid lacks.

What a cluster *is for*, and what to do about one, is the reader's: the server computes no label and keeps no verdict.
A cluster's `key` is not continuous with one a different implementation computed from the same sessions, because the
order that breaks a tie between equal weights may differ.

Both answer 501 with no telemetry stream, 503 when it cannot be read, and 400 for a number out of range.

## Report runs from any scheduler

A cron line, a systemd unit, an engine that can only send webhooks (Cronicle, Rundeck, a GitHub `workflow_run` relay) or
a producer on another host reports a run as a Step CloudEvent to the same ingest that takes machine events
([Post machine events as CloudEvents](#post-machine-events-as-cloudevents)). Declare it as a `[[producers]]` entry; a
producer that only reports runs leaves out `machines` and `actors`, needs no adapter, pulls nothing and has no Run now (so no
`run_safe`):

```toml
[[producers]]
name = "cron"
token_env = "CRON_INGEST_TOKEN"
```

Set the token where `serve` runs and send it as a bearer:

```sh
curl -X POST http://localhost:8766/api/machine-events -H "Authorization: Bearer $CRON_INGEST_TOKEN" \
  -H "Content-Type: application/cloudevents+json" \
  -d '{"specversion": "1.0", "id": "2026-10-03-start", "source": "cron", "type": "StepStarted", "subject": "2026-10-03",
       "data": {"workflow": "nightly", "status": "running"}}'
```

A Step event is `type` `StepStarted` or `StepFinished` with no `machine`. `subject` is the run's id; `data` holds the
`workflow`, the `status` (`not_started`, `queued`, `running`, `succeeded`, `failed`, `aborted` or `skipped`) and, for a
step's own entry, `step` and optionally `depends`, the steps it waits on. A run's own entry names no `step`. The page
draws an accepted event as `pushed/<source>/<workflow>`. A workflow no adapter lists is drawn from the step graph its
events add up to, and that graph is kept in the history store across restarts. A token writes only as its own
producer: a missing or wrong token answers 401, another producer's `source` 403, an event the contract does not allow
400, and none of them writes anything; the other answers are the machine events' table below.

## Post machine events as CloudEvents

A build job, a bot or any service that is not on the host posts a lifecycle machine's event over HTTP as a
[CloudEvents](https://cloudevents.io) 1.0 JSON event. Declare the producer, set its token in the server's
environment, and the server accepts `POST /api/machine-events` (404 until one is declared):

```toml
[[producers]]
name = "ci-bot"
token_env = "CI_BOT_TOKEN"
machines = ["delivery"]
actors = ["ci"]
```

```bash
curl -X POST "$STARPULSE_URL/api/machine-events" \
  -H "Authorization: Bearer $CI_BOT_TOKEN" -H "Content-Type: application/cloudevents+json" \
  -d '{"specversion": "1.0", "id": "build-41", "source": "ci-bot", "type": "BUILT", "subject": "PROJ-1",
       "time": "2026-10-18T22:00:00Z", "machine": "delivery", "actor": "ci", "data": {"sha": "abc123"}}'
```

`application/cloudevents-batch+json` takes a JSON array of up to 200 such events. The attributes map to a
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
a `machine:events` row like any other: it moves the task on the page and in the `/api/events` stream. The answers:

| Status | Meaning |
|---|---|
| 201 | every event is in the log |
| 400 | not JSON, a wrong content type, `specversion` other than `1.0`, an event or actor the machine does not declare, a machine the server does not draw, an entry keyed by neither or both of `subject` and `run`, a bad `time`, or `data` that is not an object |
| 401 | a missing or unknown token |
| 403 | a `source`, `machine` or `actor` the producer is not declared for |
| 413 | `data` over 8 KiB, or a body over the ingest's size limit |
| 503 | the event log did not take an entry; every entry has a stable id, so post the batch again |

### Over gRPC

The same ingest is served on the same port as gRPC: service `starpulse.v1.CloudEventsIngest`, methods `Publish`
(one `io.cloudevents.v1.CloudEvent`) and `PublishBatch` (a `CloudEventBatch` of up to 200), both answering
`google.protobuf.Empty`. The token is the `authorization` metadata, `Bearer <token>`. Attributes are the table above's,
carried in the event's `attributes` map (`time` as `ce_timestamp` or an RFC 3339 `ce_string`); `data` is JSON text or
bytes, never a protobuf `Any`. The checks and the all-or-nothing batch are the HTTP ingest's; `grpc-status` arrives in
the HTTP/2 trailers. A refusal's HTTP status maps to a code:

| HTTP | gRPC |
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
run_safe = ["ui-preview.yml"]
```

- **Opt-in worker.** `serve` starts none of this adapter: run `starpulse worker github-actions --config <this file>`. It
  beats into the event log, and with the worker down or never started the page shows the instance with the error "the
  `<name>` worker has not reported" or "last reported Ns ago" (a beat older than 60 s).
- **Credentials** come from the environment: `GITHUB_TOKEN` or `GH_TOKEN` (read and `actions: write` on the repository),
  and `GITHUB_API_URL` for GitHub Enterprise Server. Without a token the repository is still read, at GitHub's lower
  unauthenticated rate limit, and nothing starts.
- **Run now** dispatches the workflow on the default branch (`workflow_dispatch`) and answers its run id. It is drawn
  only on a `run_safe` workflow whose file declares `workflow_dispatch`; any other workflow is refused.
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

- **Opt-in worker.** `serve` starts none of this adapter: run `starpulse worker systemd --config <this file>` on the
  host whose timers it reads. The page shows an instance whose worker never reported or stopped, as for the other
  opt-in workers.
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
  re-reads only that timer, a third of a second after the signals settle. The whole allowlist is listed every 10 minutes
  as a backstop, and every 30 s while a monitor is down or the last read failed. Idle, the adapter starts no `systemctl`
  between those. Each `gdbus` child ends with the stream that reads it (terminated when the stream closes, SIGTERM from the
  kernel when its parent thread dies), so a restart leaves none behind. The adapter reads no event-log entries. There is no Run now: starting a root unit needs a polkit grant,
  so the adapter offers no start. `systemctl` and `gdbus` (`libglib2.0-bin`) must run on the host that serves StarPulse.

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
