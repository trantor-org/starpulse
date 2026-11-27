# Compatibility

## Public surface

What a release keeps compatible; a minor `0.y` release may break it, and its notes say so. Everything else in the package is
internal and can change in any release.

- The `starpulse` command line: its verbs, their JSON output and their exit codes ([each verb](cli.md)). The task write
  verbs are `task create TITLE [--brief --priority --impact --urgency --tier --milestone --profile --status --type --label --dependency --ac
  --reference --documentation --dod]`, which
  returns `{task}`; `task edit TASK [--title --type --priority --impact --urgency --tier --milestone --label --dependency --reference
  --documentation --modified-file --description --plan --reason --notes --append-notes --final-summary --ac --reword-ac
  --remove-ac --check-ac --uncheck-ac --dod --reword-dod --remove-dod --check-dod --uncheck-dod --comment --base]`,
  which returns
  `{task, changed}` and is refused whole (exit 1) when a field it changes is stale against its base;
  `task profile TASK PROFILE`, which returns `{task, profile, changed}`; `task archive TASK... [--reason]`, which archives
  every key in one `DELETE /api/tasks/{id}` each and returns `{archived}`, or is refused (exit 1) with `{archived, refused}`
  when any key was refused, the others still archived (an agent's archive of an open task is a request the task actor carries out); `task restore TASK`, which returns `{task}` and is refused (exit 1) for a task that is open, not archived or
  whose file name is taken; `task retire TASK`, which returns `{task}` and is refused (exit 1) for a task that is open;
  `task retired [TASK]`, which returns `{tasks}`, each `{task, name, text}`; `task cold-done`, which returns `{tasks}`, every Done task past its hot day, newest first; `task complete TASK`, which returns `{task}` and is refused (exit 1) for a task that is not Done;
  `task dispatch TASK --session S`, which returns `{ok, task, session, reason, skill}` and is refused (exit 1) when another session holds the task or the lane is wrong; the task actor pins the session from the event it publishes, so the reply is not the pin;
  `task park TASK`, which returns `{ok, task, to, assignee, reason, skill}` ([cli](cli.md)) and is refused (exit 1) with the reason and skill of the guard or rule that judged it; and
  `task checkpoint-ac TASK CRITERION EVIDENCE`, which returns `{task, criterion, changed}` and is refused (exit 1) for a
  criterion the task lacks. Each exits 0 on success, 1 refused, 2 usage, 3 when the board cannot write tasks and, for
  every verb but `create`, 4 for an unknown task.
- `starpulse import-history`, and the JSON Lines it reads: one `{event_id, task, lane, time}` object per line ([format](cli.md#importing-a-boards-history)).
- The documented entry point `python -m starpulse.runtime.claude_code`, which receives Claude Code's OTLP log
  exports.
- The `spend` field of a task in `POST /graphql` (`SpendPhase` in `tasks.graphql`): the task's tokens by phase with the weighted total and
  norm flag (see [Connect sources](sources.md#report-each-tasks-spend-by-phase)).
- `starpulse search QUERY` and its routes `GET /api/search?q=` and `GET /api/search/similar?q=` (`--similar`, which waits to embed a new query): the board's tasks ranked by an instance-local full-text index, as `{query, hits}` ([each verb](cli.md)); the index and its module are internal.
- The board machine's `mainLine` and `tiers` in the `Machine` record of `api.schema.json`: `tiers` is a list of
  tiers, each a list of state ids, that the Star Map draws left to right, one grid cell per tier with a tier's states
  stacked in its cell. A tier of one state beside another such tier sits high or low by its state id, so the state
  keeps its side when a neighbouring tier or state is added or removed. A state no tier names is drawn with the tier at
  the mean of the tiers its transitions join it to, stacked in that tier or in a tier of its own right after it,
  whichever lets the sun draw larger; one with no transition to a state a tier names takes a tier of its own after the
  last. An id no state has is ignored, and a machine with no `tiers` (or an empty list) draws the Board's own columns,
  as before. The Star Map draws one row unless a second row makes the sun more than 5% larger, and keeps each state's
  footprint the same whatever it holds.
- The config file's keys, among them
  the `[analytics]` table's `roots`, `injected_openings`, `operator_tools`, `claims`,
  `completion_skill`, `completion_call`, `eval_attribute`, `ladder`, `phases`, `default_repo`, the `[analytics.weights]` table, the optional `[analytics.labeller]` table's `url`, `model`, `instructions`,
  `criteria` and `timeout`, and the `[search]` table's optional `embeddings_url`, `model` and
  `token_env` ([Config file](serving.md#config-file)),
  and the machine YAML with its JSON Schema (`machine.schema.json`).
- A machine state's optional `label` (the name a person reads, the id when absent) and `aliases` (names retired from the state that
  history still holds), which `starpulse machine lanes` prints.
- A machine state's optional `role` key: `resting`, `waiting_on_fact`, or `waiting_on_person`; a state flagged
  `initial` or `final` has that role already. `Compiled.roles` maps every state id to its role (`None` when it declares none) and
  `role_of(compiled, state)` answers it, raising `KeyError` for a state the machine lacks. StarPulse code reads roles,
  never a deployment's state names. The snapshot serves it as the `role` of each `Machine.states` entry in
  `api.schema.json` (`null` when none), and the Kanban draws it on each column header. A state the machine's `rests`
  names ends the lifecycle though an event leaves it, so it is served as `final`.
- A machine state's optional `waits` key: a map from a fact kind (`pr_terminal`, `pr_merged`, `pr_closed_unmerged`, `pr_closed_unmerged_complete`, `pr_merged_unfinished`, `pr_ready`, `pr_failing`, `pr_draft`, `pr_conflicting`, `deps_done`,
  `deps_done_with_pr`, `deps_unresolved`, `owner_stale`, `criteria_met` or `overdue`) to the event that leaves the state when that fact holds. The loader refuses an
  unknown fact kind and an event that is not a transition out of the declaring state, naming the state and event, and
  exposes the declared map as `Compiled.waits` (`{state id: {fact kind: event}}`; a child flow's states carry their
  `<state>_<child state>` id). Declaring `waits` fires nothing by itself: the board hands the Board machine's map
to the server as `Board.waits`, and the task actor (`[board.actor]`, [Task actor](serving.md#task-actor)) fires the event
when the fact holds; `Board.holds` withholds `deps_done` with reasons; `Board.unfinished` lists the work a merged task still has, which holds `pr_merged_unfinished`. The actor's series on `GET /metrics` are
`starpulse_task_actor_refusals_total`, `starpulse_task_actor_latency_seconds`, `starpulse_task_actor_projection_seconds`,
`starpulse_task_actor_handoff_seconds`, `starpulse_task_merge_move_seconds`, `starpulse_task_park_release_seconds`, `starpulse_task_receipt_done_seconds`, `starpulse_task_actor_pin_held`,
`starpulse_task_actor_recovery_finished` and `starpulse_task_actor_merged_review_waiting`.
`starpulse_board_lane_unattributed_total` counts the `board:lanes` entries appended since `serve` started that name no actor.
`starpulse_autopilot_enabled` (0/1), `starpulse_autopilot_switch_changed_timestamp_seconds` (when the `scheduler.enabled`
switch was last written), `starpulse_autopilot_ledger_runs` (rows in the run ledger) and
`starpulse_autopilot_decisions_total{verdict="admitted|refused"}` (verdicts the loop has logged, kept in the store) read
the store on each scrape.

The modules an adapter may import. A context package exports exactly the names in its `__all__`; a `runtime` module
is public for the names listed here:

- `starpulse.board`: the board the server calls directly (`Board`, `Written`, the writer, task, milestone and doc protocols, and the `NativeScan` scan), the feed the board places tasks on (`BoardFeed`, `BoardStore`, `Followed`, `Resumable`) and `CommitKeys`.
- `starpulse.contracts`: the board (a `BoardTask` carries `acceptance_criteria` with `acceptance_checked`, `pause_reason` and `notes` beside its `description`), machine-event, CloudEvent (`CloudEvent`, the ingest's and `starpulse event emit`'s model), run-event (`RunEvent`), lane-event (`LaneEvent`), verdict-event (`VerdictEvent`), runs (`Dag`, `RecentRun`) records, their JSON Schemas, `EVENT_STREAMS` (the record of each event log stream), and `RunsSink`.
- `starpulse.event_log`: the database event log readers tail; [Build a consumer](consumers.md) shows a reader that keeps its cursor in its own store.
- `starpulse.flow_metrics`: the history store, and placing a task's events on a machine.
- `starpulse.harness_telemetry`: loading the harness file and the tiers and efforts an agent profile names, and decoding Claude Code's OpenTelemetry log export.
- `starpulse.machine_engine`: loading and validating a machine and the `Registry` of guards and actions, replaying recorded moves (`check_lanes`, `check_events`) and event traces (`conform`, `replay`, `runs`) against it, the paths and gate `bypasses` it generates, how it is described to the page and its workflows are named, and drafting one from a Mermaid state diagram (`draft_machine`).
- `starpulse.runs`: the runs instance a config file declares (`RunsInstance`).
- `starpulse.sessions`: what an agent session did: the Activity each tool call performed (`activities`, labels with no arguments).
- `starpulse.runtime.adapter_kit`: the test kit an adapter author runs against their work, and the helpers that serve it.
- `starpulse.runtime.ephemeral_board`: `ephemeral_board(seeds)`, which opens a task per `TaskSeed` on a scratch board and returns their records (the `starpulse task show` reply) with the `WriteInstance` that wrote them, so a project tests against a board without a harness of its own; a record is read after the Board writer has folded every verb run through the instance.
- `starpulse.runtime.write_instance`: `write_instance(base)`, which serves the write routes over the board a config file names so a test writes tasks through StarPulse (`WriteInstance.run` calls a `starpulse` verb in-process).
- `starpulse.runtime.config`: loading the config file and the runs adapter a `type` names.
- `starpulse.runtime.closure`: `restarts_serve` (whether a change to the raw tables needs `serve` itself restarted).
- `starpulse.runtime.machine_files`: `import_definitions(config, base, paths=None)` and `export_definitions(config, base, out)`, which activate machine definitions from files and write the active ones out, for a project that keeps them in its repository.
- `starpulse.runtime.nats_server`: `DEFAULT_PORT`, the port the bridge's NATS server listens on when `[bridge] port` names none, for a test that must pick another.
- `starpulse.runtime.placed`: `Placed(machines=None)`, a read model over a temporary database whose `put(task)` places a `BoardTask` and whose `draw(**settings)` returns the `BoardFeed`, for a test that serves or starts a board over placed tasks.
- `starpulse.runtime.session_delivery`: `line_for(event)`, the line the bridge writes into a holding session for a delivered event, for a consumer that checks what a session reads.
- `starpulse.bridge.subjects`: `subject_for(board, entry)`, the subject the bridge publishes an event-log entry on, or `None`.
- `starpulse.bridge.subscriptions`: `parse_rules(table)`, the rules of each task kind from the `[bridge.subscriptions.<kind>]` tables, and `expand(board, templates, **values)`, their full subjects, for a consumer that checks its own subscription rules.
- `starpulse.bridge.delivery`: `Event`, the delivered event (`subject` and `payload`) that `line_for` renders.
- `starpulse.bridge.ingest`: `Producer(url, board, token)`, which publishes a CloudEvent to the board's ingest stream, for a tool that sends its events through the queue; `post(event)` returns 201 once the stream holds it, 413 over the payload limit, 0 when the server is unreachable.
- `starpulse.github.adapters.outbound.queue`: `SqlQueue(engine, consumer)`, the per-consumer queue over the durable GitHub
  inbox, for a consumer outside the package. Method contract: `claim(limit)` returns the due `Entry` list, oldest first;
  `complete(delivery_id)`, `skip(delivery_id, reason)` and `fail(delivery_id, error, fatal=, exhausted=)` settle one
  (`fail` returns the new status); `requeue(delivery_id)` and `dismiss(delivery_id)` return whether a row changed.
- `starpulse.github.adapters.outbound.inbox`: the `github_inbox` table and `SqlInbox`.
- `starpulse.github.ports.events`: `Entry`, the `delivery` and its `attempts`, and the `Queue` protocol.
- `starpulse.github.model.events`: `CONSUMER`, the queue name the GitHub inbox consumer registers under, for a consumer outside the package.
- `starpulse.pulls.adapters.outbound.pulls`: `PullStore`, the store the webhook deliveries and lifecycle events save to.
- `starpulse.views.adapters.outbound.signal_folds`: `changed(events, after, views, since=0.0)`, the stored per-session results folded past a rowid cursor, for a sink that copies only what changed.
- `starpulse.views.adapters.outbound.task_spend`: `TaskSpend(events)`, whose `catch_up()` relinks and resums the sessions whose spend fold was rewritten, for a seeder that fills the task spend a drawer reads.
- `starpulse.views.application.queries.responses`: `spend_response(folds, task, query, now)`, the task spend body the route answers and its status, for a test that checks a seeded store renders it.
- `starpulse.pulls.adapters.inbound.task_actor`: `ACTOR`, the writer name the task actor's moves and refusals carry, for a test that publishes as it.
- `starpulse.cli.agent_subscribe`: `subscribed(session, subject, config=None)`, whether a session is subscribed to a subject, for a command that must not subscribe it twice.
- `starpulse.cli.agent_wire`: `CliError`, `server_url(flag, environ)`, `get(base, path, timeout=10.0)` and `put(base, path, body)`, the server address, JSON read and JSON write a command that reads or links a task on the server makes.
- `starpulse.views.adapters.outbound.request_durations`: `CALLERS`, the first-party client names `X-StarPulse-Client` carries, for a dashboard that checks it lists each.
- `starpulse.cli.lane_mcp`: `lane_argv(tool, task, arguments)`, the `starpulse` argv a lane tool runs, for a test that checks each names a command the project defines.
- `starpulse.cli.agent_cli`: `_parser()`, the `starpulse` argument parser, for a test that checks each command form a skill shows parses.
- `starpulse.bridge.publisher`: `Publisher(url, stream, subjects)`, which creates a stream and publishes to it, for a test that needs a stream to consume.
- `starpulse.testing`: `until(condition, within=)`, the one bounded wait a test makes on a condition, returning as soon as it holds.

### Moved in 0.y

Release 0.y deleted the top-level facade modules and the `_internal` package; a context's package is its public path. Update each import as the table says. `python -m starpulse.claude_code` is now `python -m starpulse.runtime.claude_code`. The `starpulse.board_feed` logger is now `starpulse.board.model.board_feed`. `python -m starpulse.mermaid_import` is `python -m starpulse.machine_engine.adapters.mermaid_import`.

| Old path | New path |
| --- | --- |
| `starpulse.adapter_kit` (the kit) | `starpulse.runtime.adapter_kit` |
| `starpulse.adapter_kit` (`WriteInstance`, `write_instance`) | `starpulse.runtime.write_instance` |
| `starpulse.board_feed` | `starpulse.board` |
| `starpulse.config` (`Config`, `ConfigError`, `load`, `runs_adapter`) | `starpulse.runtime.config` |
| `starpulse.config` (`restarts_serve`) | `starpulse.runtime.closure` |
| `starpulse.config` (`CommitKeys`) | `starpulse.board` |
| `starpulse.config` (`RunsInstance`) | `starpulse.runs` |
| `starpulse.conformance` | `starpulse.machine_engine` |
| `starpulse.machine_definition` | `starpulse.machine_engine` |
| `starpulse.mermaid_import` | `starpulse.machine_engine` |
| `starpulse.snapshot` | `starpulse.machine_engine` |
| `starpulse.history` | `starpulse.flow_metrics` |
| `starpulse.harnesses` | `starpulse.harness_telemetry` |
| `starpulse.otlp` | `starpulse.harness_telemetry` |
| `starpulse.claude_code` | `starpulse.runtime.claude_code` |
| `starpulse._internal.*` | not public; use the context packages above |

A package test pins this list and each module's names, so adding or removing one is a reviewed change.

## Board types

A task carries an optional `type`, a free string the board gives no meaning: `starpulse` ships no built-in names.
`[board] types` in the config file (the native board's `types` setting) is an optional list of the names it may take.
With the list declared, a write that sets a type outside it is refused with the list in the reason, whichever writer
makes it: `starpulse task create` and `task edit`, the page, `PUT /api/tasks` and `PUT /api/tasks/{id}`; a task whose type is
unchanged is not refused, so narrowing the list never blocks an edit to a task already of another type. With no list,
any non-empty string lands. `starpulse board --type NAME` keeps only the tasks of that type, and each task the board
reports carries its `type` (empty when it has none).

## Board guards

`[[board.guards]]` in the config file (the native board's `guards` setting) declares record-level rules every task write
must satisfy, whichever writer makes it: `starpulse task move` and the other agent verbs, the page, and a workflow.
They are enforced where the native board lands a task write, so a move from the CLI and the same move from the page
meet the same rule and are refused with the same `reason` and `skill`, and nothing is written. The `warn_actors` setting
(a list of actors, empty by default) is the one exception: a move by an actor it lists that breaks a lane rule (`on` with
`to` or `from`) lands, and the answer carries `"ok": true` and `warnings`, the `reason` of each rule it broke. A `write`
or `create` rule still refuses that actor. The `moves` field of a task in `POST /graphql` carries the board's guarded verdict on every lane for one task, that
actor's with the same rules as `warnings` (`reason`, `skill` each); the stream's snapshot leaves its `moves` unguarded
(judging every card each cycle costs seconds), and `GET /api/task/<id>` carries none. The kanban queries the field when a
card is dragged, dropped or opened, and lists the warnings in a confirm box before it posts the move; Cancel writes
nothing.
`[[board.entry]]` declares what entering a lane does to a task, for every writer: `{ lane, set }` fills the front matter
fields the task holds none of, with `{ matrix = true }` (`profile` from `[board.default_profiles]` by the
task's `kind-*` and `size-*` labels), before the lane's rules judge the write. A board with no rules accepts every write it accepted
before, and a rule it cannot read (an unknown key or primitive, a missing `reason`, a bad pattern) is a startup error
naming `guards[N]`.

Release note: guards were `[[board.rules]]`. A config that still has that table is refused at startup with an error naming
`[[board.guards]]`; rename the table, nothing else changes. Every entry path is judged by the same enforcement point: the
config file's table, the task write verbs, the page, and `PUT /api/tasks` and `PUT /api/tasks/{id}`.

A rule is a table of:

| Key | Holds |
|---|---|
| `on` | which writes it judges: `{ to, from }` (a write that enters `to`, from one of `from` when given; either is a state name or a list), `{ to, from, while = true }` (also a write that leaves the task in a `to` state), `{ write = true }` (every write, create and archive included) or `{ create = true }` (a create only; an edit, move or archive is never judged) |
| `require` | one primitive the task as it will be after the write must satisfy |
| `reason` | the refusal text the CLI and the page show (required) |
| `skill` | the skill that satisfies the rule, carried with the refusal (optional) |
| `unless_actor` | actors the rule does not judge: `operator`, `agent` or `<instance>/<workflow>` as a machine's `writers` spell them (optional) |

A primitive is a one-key table naming its kind (`require = { label = { contains = "adr-needed" } }`); the table gives
the value under that key:

| Primitive | Value under the key | Holds when |
|---|---|---|
| `field` | `{ field = "references", matches = "/pull/\\d+$", in = [...], min = 1 }` | a scalar or list front matter field has at least `min` (default 1) items that match the pattern and are in the set; one of `matches`, `in` or `min` is required |
| `label` | `{ contains = "adr-needed" }`, `{ starts_with = "board-lint-" }` or `{ prefix = "size-", in = [1, 2, 3, 5, 8] }` | the task has the label, has a label that starts with the text, or has a label with the prefix and every such label is the prefix and a value of `in` |
| `section` | `{ heading = "Needs attention", nonempty = true }` or `{ heading = "Needs attention", not_matching = "\\bTASK-\\d+\\b", except_self = true }` | the body has a `## <heading>` section (up to the next `##`); with `nonempty` it is not blank; with `not_matching` its text, an absent section's counting as empty, does not match, `except_self` first dropping the task's own id |
| `dependencies` | `{ all_in = ["Done"] }` | every task in `dependencies` is in one of the named states; a dependency with no task file is in none, and no dependencies holds |
| `checklist` | `{ sections = ["acceptance_criteria", "definition_of_done"], all_checked = true }` or `{ sections = ["acceptance_criteria"], min_items = 3 }` | every item of the named lists is checked (an empty or absent list holds), and/or the named lists hold at least `min_items` items between them; `all_checked` and `min_items` combine |
| `unique` | `{ field = "source" }` | no other open task (under `tasks/`, not in the Done state) holds a value the task's scalar or list front matter `field` holds; a task with no value holds. A task's own id is not another task |
| `names_ids` | `{ from = "dependencies", matches = "TASK-\\d+", in = "source" }` | every match of the pattern in the values of front matter field `from` is also a match in the values of field `in` of `named` (optional, default the `matches` pattern), compared without regard to case; a `from` with no match holds, and a refusal names the IDs left out |
| `retained` | `{ region = "acceptance_criteria", matches = "^- \\[[xX]\\] " }` | every line of the region that matches the pattern before the write (a checked criterion) is still there, unedited, after it; a create holds |
| `no_implied_dependency` | `{}` | no dependency the write adds is already reached through another entry of `dependencies` (through the dependencies of the tasks it names, `TASK-N#K` counting as `TASK-N`); an edge recorded earlier is not judged |
| `pull_proof` | `{ region = "comments", matches = "^Merge proof" }` | each pull request URL in `references` is named by a line of the region (`region` defaults to `comments`) that the pattern selects: by its URL, by `owner/repo#N` or `repo#N`, or by a bare `#N` when no other cited pull request has that number; a task citing none holds |
| `matrix_profile` | `{}` | the task's `profile` is the one the board's `default_profiles` give its `kind-*` and `size-*` labels; a task lacking either label, or a cell, holds. It is the plain cell: the lifts the CLI adds for UI and attended work are not expressed, so a row that needs them leaves those tasks to its `any_of` alternative |
| `before` | `{ section = { heading = "Needs attention", not_matching = "\\?" } }`, any primitive | the task as it was before the write satisfies the nested primitive; a create had no earlier task, so it holds |
| `body` | `{ region = "description", matches = "AGENTS\\.md\\b" }` | the regular expression is found in the body, or in one region of it (`description`, `plan`, `acceptance_criteria`, `definition_of_done`, `final_summary`, each between its `<!-- ...:BEGIN -->` and `:END -->` markers); an absent region holds nothing |
| `block` | `{ heading = "Start Criteria", key = "start_criteria" }` | the section under the `## ` heading holds a fenced `yaml` block that parses to a mapping whose `key` is a non-empty list; an absent section, fence or list fails |
| `readable` | `{ headings = [{ name = "Outcome", max_sentences = 1 }, { name = "Terms", optional = true }, { name = "Scope", no_paths = true }], commands = ["uv run", "git"], max_paths_per_sentence = 2, blast_radius = { heading = "Blast Radius", stops = "Stop Conditions", rollback = "Rollback" } }` | the description (the `DESCRIPTION` region, else the body) opens with its first `## ` heading and holds the `headings` in order, each required unless `optional`; in a section, a line starting with a `commands` prefix sits in a fenced block, the sentences number at most `max_sentences`, a `no_paths` section names no path, a path in prose sits in backticks, and no sentence names more than `max_paths_per_sentence` paths; the `blast_radius` section opens with `reach N · data N · undo N · detect N. <sentence>`, N 0 to 3, an axis at `stop_at` (default 3) or more is named in a `stops` section line, and `undo` at `rollback_at` (default 2) or more needs the `rollback` section. `board_written` lists `## ` headings the board writes (`Needs attention`, `Start Criteria`), which are stripped before the older-description comparison and the judging, in any position. The refusal is the rule's `reason`, a colon and the first broken rule with its line in the description |
| `post_merge_checks` | `{}` | the body's `## Post-merge Checks` section is absent, or holds a fenced `yaml` block whose `post_merge_checks` list is valid (see Post-merge checks); a malformed check fails |
| `qa_verdict` | `{ lens = "ui" }` | the task's latest qa round recorded a `LENS_PASSED`, `LENS_UPHELD` or `LENS_DISPUTED` verdict at that lens; a skip, a timeout, no round, or a board with no history store does not hold. The store keeps a qa event by task and name alone, so the lens is the state the qa machine (`.starpulse/machines/qa.yaml`) held the task in when the event arrived, replayed as the ingest places it; a round opens at `ROUND_STARTED` or at an event after a final state. It reads the history store, so the standing verdict leaves it out |
| `pulls_ready` | `{}` | every pull request URL in `references` is in the PR store and is either merged, whatever its `checks`, or open and not a draft with `checks` `pass` (a pull request closed without merging is skipped while another cited one is not closed, and fails only when every cited one is closed); a task citing none holds. A pull request the store lacks, or a board not yet started, fails the rule; `starpulse pull show OWNER/NAME#N` tells which cause refused it. Only a URL of the form `https://github.com/OWNER/NAME/pull/N` counts as a citation: one with a suffix such as `/files` or `#fragment` is not read. It reads the store, never GitHub, so the standing verdict leaves it out |
| `pulls_failing` | `{}` | some pull request URL in `references` is in the PR store, `OPEN`, and has `checks` `failing`; a task citing none, or only pending, passing or merged ones, fails |
| `pulls_clear` | `{}` | every pull request URL in `references` is in the PR store and either `MERGED` or has no unresolved review thread and is `MERGEABLE` (an open `CONFLICTING` or `UNKNOWN` one fails; GitHub reports a merged one `UNKNOWN`); a closed unmerged one is skipped while another cited one is not closed, as in `pulls_ready`; a task citing none holds. It reads the store, except that an open pull request whose stored `mergeable` is not `MERGEABLE` is settled from GitHub (`gh api`; an uncomputed or unreadable answer keeps the stored value), since no event clears a stored conflict after a push; the standing verdict leaves it out. Paired with `pulls_ready` on `to = "Review"`, a ready pull request with a finding is refused and the task actor hands the holder the refusal through the `REVIEW_REFUSED` machine event |
| `pulls_changed` | `{ files = ["src/web/**", "*.html"], matches = "render evidence" }` | no cited pull request changed a file matching a glob of `files` (`fnmatch`, `*` crosses `/`); otherwise a checked `- [x]` line of the task body matches `matches` (a regular expression), or every pull request with a matching file has a body that matches. A checked `- [x]` line matching `matches` clears the rule first, even when a file list is unknown. A pull request whose changed files the store does not know (saved before they were kept, opened by an event no read of GitHub has followed, or with more than 100 files) fails the rule; `starpulse pull show OWNER/NAME#N` prints its `files`. A cited pull request whose head branch names another task (`claude/task-12-page` cited by `TASK-7`) is skipped: that task carries its own evidence. Both keys are required, `files` non-empty; it reads the store, never GitHub |
| `archive_cited` | `{ prefixes = ["Archive requested:", "Archived:"], superseded = "superseded by", obsolete = "obsolete:", exempt = ["done"] }` | the task's last comment is not an archive comment (one starting with a `prefixes` entry), the task's state is in `exempt`, or it cites no pull request that is open or merged; otherwise no cited pull request is merged and the reason after the prefix holds `<superseded> <ID>` naming another task on the board or `<obsolete>` followed by text. All four keys are required; it reads the store, never GitHub |
| `all_of`, `any_of`, `exactly_one`, `none_of` | a non-empty list of primitives | all, at least one, exactly one or none of them hold |

`readable` counts and prefix-matches; it judges no meaning. Its blind spots: a command outside the `commands` prefix list
passes; a path is a token with two or more slashes, a leading `/`, `.` or `~`, or a file extension, so `docs/specs` and
`and/or` pass; a sentence count cannot tell a summary from a second sentence; a well-formed `Blast Radius` with a wrong
score passes. Each board task also carries the rules' standing verdict as `readable` on its snapshot, feed and
`task show` record: empty when its description reads well (or the task is settled), else the first broken rule with
its line, so a page can badge a description written before the rules without refusing it until its next edit.

A write names its actor, which `unless_actor` matches. `PUT /api/tasks` and `PUT /api/tasks/{id}` and `DELETE /api/tasks/{id}`
take an optional `actor`, `session` and `harness`, each non-empty text (anything else is a 400). Every write parses its body through the request model of its route, so a body that is not a JSON object, names a key the route does not take or holds a field of the wrong type is a 400 `invalid request: <field>: <reason>` for its first fault, a key the route does not take before any other. The page names
`operator`; `starpulse` verbs name `agent`, their session and their harness. A write naming no actor is `agent` when it
names a session and `anonymous` when it names none, never `operator`, so an unnamed write is not judged as the
operator's. The write's `board:lanes` row carries all three, and a create stamps `created_by: <harness>:<session>` in
the task (`anonymous` when it names no session). `POST /api/start` takes an optional `actor` and calls a board writer's
`assign` with it only when named.

`PUT /api/tasks/{id}/links` and `DELETE /api/tasks/{id}/links` store and remove a task's pull request link, keyed by the task's UUID
(`starpulse_task_links`, events `link-written` and `link-removed` on the `task-link` stream), so a renamed task keeps its links.
The body names the `session` and `harness` asking, a `role` (`delivers` or `cites`) and exactly one of `ref` (`change:<adapter>:<id>`)
and `url`, which the configured forge turns into a `ref`. Only the session that holds the task writes: any other is 403 `NotHolder`
naming the holder. A `delivers` pull request another task already delivers is 409 `DeliveredElsewhere`, a `url` no forge recognises
is 400 `UnrecognisedUrl`, and a link already stored is a 200 that writes nothing (201 when written). A `DELETE` of a link the task
lacks is 404.

## Post-merge checks

A task declares what must hold after its merge in a `## Post-merge Checks` section: a fenced `yaml` block whose
`post_merge_checks` key is a list of checks. A check is `{id, text, within, pass}` with optional `when` and `fail`:
`id` names it (unique in the task), `text` states the claim, `within` is the deadline after the merge as a positive
duration (`90m`, `12h` or `1d`), and `when`, `fail` and `pass` are criteria. A criterion is a table with a `kind` the
client names, the keys that kind reads and an optional `id`. StarPulse evaluates no criterion, so it accepts any kind,
and sets no ceiling on `within`; the client decides both.

```yaml
post_merge_checks:
  - {id: live, text: The service answers, within: 1d, pass: {kind: prom, expr: up}}
```

A check's verdict is a comment on its task, `[post-merge-check] <id> PASS` or `MISS`, then `Fix: <task>` for a miss and the
evidence; a `PASS` is written as the `comment` of `PUT /api/tasks/{id}`.

## Versioning

StarPulse is versioned `0.y.z` until its interfaces settle: a minor version can break the config file, the adapter
contract or the command line, and a patch release never does. Each release is a
[GitHub Release](https://github.com/trantor-org/starpulse/releases) whose notes list the pull requests it contains.
