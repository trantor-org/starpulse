# Compatibility

## Public surface

What a release keeps compatible; a minor `0.y` release may break it, and its notes say so. Everything else in the package is
internal and can change in any release.

- The `starpulse` command line: its verbs, their JSON output and their exit codes ([each verb](cli.md)). The task write
  verbs are `task create TITLE [--description --priority --impact --urgency --milestone --profile --status --type --label --dependency --ac
  --reference --documentation --dod]`, which
  returns `{task}`; `task edit TASK [--title --type --priority --impact --urgency --milestone --label --dependency --reference
  --documentation --modified-file --description --plan --notes --append-notes --final-summary --ac --reword-ac
  --remove-ac --check-ac --uncheck-ac --dod --reword-dod --remove-dod --check-dod --uncheck-dod --comment --base]`,
  which returns
  `{task, changed}` and is refused whole (exit 1) when a field it changes is stale against its base;
  `task profile TASK PROFILE`, which returns `{task, profile, changed}`; `task archive TASK... [--reason]`, which archives
  every key in one `POST /api/archive` and returns `{archived}`, or is refused (exit 1) with `{archived, refused}`
  when any key was refused, the others still archived; `task verdict TASK CHECK pass|miss`, which returns `{task, check, verdict}`, and `task miss TASK CHECK --title`,
  which returns `{task, check, verdict, fix}`, each refused (exit 1) for a check that is undeclared or already judged; `task restore TASK`, which returns `{task}` and is refused (exit 1) for a task that is open, not archived or
  whose file name is taken; `task retire TASK`, which returns `{task}` and is refused (exit 1) for a task that is open;
  `task retired [TASK]`, which returns `{tasks}`, each `{task, name, text}`; `task import-retired FILE...`, which returns
  `{tasks}`, the imported ids; `task complete TASK`, which returns `{task}` and is refused (exit 1) for a task that is not Done;
  `task claim TASK`, `task park TASK` and `task review TASK`, which return `{ok, task, to, assignee, reason, skill}` ([cli](cli.md)) and are refused (exit 1) with the reason and skill of the guard or rule that judged them; and
  `task checkpoint-ac TASK CRITERION EVIDENCE`, which returns `{task, criterion, changed}` and is refused (exit 1) for a
  criterion the task lacks. Each exits 0 on success, 1 refused, 2 usage, 3 when the board cannot write tasks and, for
  every verb but `create`, 4 for an unknown task.
- `starpulse import-history`, and the JSON Lines it reads: one `{event_id, task, lane, time}` object per line ([format](cli.md#importing-a-boards-history)).
- The documented entry point `python -m starpulse.runtime.claude_code`, which receives Claude Code's and Codex's OTLP log
  exports, `python -m starpulse.runtime.cursor`, which reads Cursor's agent transcripts, and `python -m starpulse.runtime.cursor_context`,
  which restarts a Cursor task session past its context limit.
- `GET /api/analytics/sessions` and its body in `api.schema.json`: session and slice health from those exports (see
  [Connect sources](sources.md#measure-session-and-slice-health)).
- `GET /api/analytics/steps` and its body in `api.schema.json`: one record per model request, with the skill in
  force, the activities and keys of its tool calls and its tokens (see
  [Connect sources](sources.md#read-each-step-of-a-session)), and `starpulse analytics steps [--hours]` that reads it.
- `GET /api/analytics/transitions` and `GET /api/analytics/cells` and their bodies in `api.schema.json`: the cost of each
  skill within a kind and size of task, and the median steps per clean completion of each kind and size (see
  [Connect sources](sources.md#price-each-transition-and-report-each-cell)), and `starpulse analytics transitions|cells
  [--hours]` that read them.
- `GET /api/analytics/graph`, `GET /api/analytics/stages` and `GET /api/analytics/diff` and their bodies in
  `api.schema.json`: the branching directly-follows graph of each transition with its judgement cuts, the sub-stages
  mined at those cuts for the stretches no skill governs with their stability from one window to the one before, and
  each transition's reference run against its slowest clean run (see
  [Connect sources](sources.md#graph-a-transitions-activities-and-diff-a-fast-run-against-a-slow-one)), and `starpulse
  analytics graph|stages|diff [--hours]` that read them.
- `GET /api/analytics/cost-to-go` and its body in `api.schema.json`: the expected agent steps to a run's end from each
  state of each skill machine, with the times the state was left (see
  [Connect sources](sources.md#read-the-steps-still-to-come-from-each-state-of-a-skill-machine)).
- `starpulse search QUERY` and its route `GET /api/search?q=`: the board's tasks ranked by an instance-local full-text index, as `{query, hits}` ([each verb](cli.md)); the index and its module are internal.
- `GET /api/analytics/missed-loads` and `GET /api/analytics/trace-clusters` and their bodies in `api.schema.json`:
  the skills a session did not load for work that should have loaded them, and the work that recurs across sessions
  with the sessions an eval run stamped (the `[analytics]` `eval_attribute`) left out (see
  [Connect sources](sources.md#find-missed-skill-loads-and-recurring-work)).
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
  the `[analytics]` table's `roots`, `stop_activities`, `lifecycle_skills`, `injected_openings`, `operator_tools`, `claims`,
  `completion_skill`, `completion_call`, `eval_attribute`, `ladder`, `default_repo`, the `[analytics.weights]` table, the optional `[analytics.labeller]` table's `url`, `model`, `instructions`,
  `criteria` and `timeout`, each `[[analytics.skill_loads]]`'s
  `skill`, `activities`, `title` and `label`, and each `[[analytics.skill_machines]]`'s `skill` and `stages` (`name`,
  `activities`, `ok`), and the `[search]` table's optional `embeddings_url`, `model` and
  `token_env` ([Config file](serving.md#config-file)),
  and the machine YAML with its JSON Schema (`machine.schema.json`).
- A machine state's optional `role` key: `resting`, `waiting_on_fact` or `waiting_on_person`; a state flagged `initial`
  or `final` has that role already. `Compiled.roles` maps every state id to its role (`None` when it declares none) and
  `role_of(compiled, state)` answers it, raising `KeyError` for a state the machine lacks. StarPulse code reads roles,
  never a deployment's state names. The snapshot serves it as the `role` of each `Machine.states` entry in
  `api.schema.json` (`null` when none), and the Kanban draws it on each column header. A state the machine's `rests`
  names ends the lifecycle though an event leaves it, so it is served as `final`.
- A machine state's optional `waits` key: a map from a fact kind (`pr_terminal`, `pr_merged`, `pr_merged_planned`, `pr_merged_unfinished`, `pr_ready`, `pr_failing`, `pr_draft`, `pr_conflicting`, `deps_done`,
  `deps_done_with_pr`, `deps_unresolved`, `criteria_met` or `criteria_unmet`) to the event that leaves the state when that fact holds. The loader refuses an
  unknown fact kind and an event that is not a transition out of the declaring state, naming the state and event, and
  exposes the declared map as `Compiled.waits` (`{state id: {fact kind: event}}`; a child flow's states carry their
  `<state>_<child state>` id). Declaring `waits` fires nothing by itself: a board adapter hands the Board machine's map
to the server as `Board.waits`, and the task actor (`[board.actor]`, [Task actor](serving.md#task-actor)) fires the event
when the fact holds; `Board.holds` withholds `deps_done` with reasons; `Board.unfinished` lists the work a merged task still has, which holds `pr_merged_unfinished`. The actor's series on `GET /metrics` are
`starpulse_task_actor_refusals_total`, `starpulse_task_actor_latency_seconds`, `starpulse_task_actor_projection_seconds`,
`starpulse_task_actor_handoff_seconds`, `starpulse_task_actor_criteria_errors` and `starpulse_task_actor_pin_held`.
`starpulse_board_lane_unattributed_total` counts the `board:lanes` entries appended since `serve` started that name no actor.
`starpulse_autopilot_enabled` (0/1), `starpulse_autopilot_switch_changed_timestamp_seconds` (when the `scheduler.enabled`
switch was last written), `starpulse_autopilot_ledger_runs` (rows in the run ledger) and
`starpulse_autopilot_decisions_total{verdict="admitted|refused"}` (verdicts the loop has logged, kept in the store) read
the store on each scrape.

The modules an adapter may import. A context package exports exactly the names in its `__all__`; a `runtime` module
is public for the names listed here:

- `starpulse.board`: the board adapter seam (`Board`, `Written`, the writer, task, milestone and doc protocols, and the `UpstreamBacklog` reference adapter), the feed a board adapter places tasks on (`BoardFeed`, `BoardStore`, `Followed`, `Resumable`) and `CommitKeys`.
- `starpulse.contracts`: the board (a `BoardTask` carries `acceptance_criteria` with `acceptance_checked`, `pause_reason` and `notes` beside its `description`), machine-event, CloudEvent (`CloudEvent`, the ingest's and `starpulse event emit`'s model), run-event (`RunEvent`), lane-event (`LaneEvent`), verdict-event (`VerdictEvent`), runs (`Dag`, `RecentRun`) records, their JSON Schemas, `EVENT_STREAMS` (the record of each event log stream), and `RunsSink`.
- `starpulse.event_log`: the database event log readers tail; [Build a consumer](consumers.md) shows a reader that keeps its cursor in its own store.
- `starpulse.flow_metrics`: the history a board adapter may keep itself, and placing a task's events on a machine.
- `starpulse.harness_telemetry`: loading the harness file and the tiers and efforts an agent profile names, and decoding Claude Code's OpenTelemetry log export.
- `starpulse.machine_engine`: loading and validating a machine and the `Registry` of guards and actions, replaying recorded moves (`check_lanes`, `check_events`) and event traces (`conform`, `replay`, `runs`) against it, the paths and gate `bypasses` it generates, how it is described to the page and its workflows are named, and drafting one from a Mermaid state diagram (`draft_machine`).
- `starpulse.runs`: the runs instance a config file declares (`RunsInstance`).
- `starpulse.sessions`: what an agent session did: the Activity each tool call performed (`activities`, labels with no arguments), and session and slice Health folded from Claude Code's and Codex's log exports (`session_health`, `slice_health`) as the DTOs `GET /api/analytics/sessions` serves.
- `starpulse.runtime.adapter_kit`: the test kit an adapter author runs against their work, and the helpers that serve it.
- `starpulse.runtime.write_instance`: `write_instance(base)`, which serves the write routes over the board a config file names so a test writes tasks through StarPulse (`WriteInstance.run` calls a `starpulse` verb in-process).
- `starpulse.runtime.config`: loading the config file and the runs adapter a `type` names.
- `starpulse.runtime.closure`: `CONFIG_OWNERS` (the processes that read each key) with `restarts_serve` (whether a change to the raw tables needs `serve` itself restarted).

### Moved in 0.y

Release 0.y deleted the top-level facade modules and the `_internal` package; a context's package is its public path. Update each import as the table says. `python -m starpulse.claude_code`, `python -m starpulse.cursor` and `python -m starpulse.cursor_context` are now `python -m starpulse.runtime.claude_code`, `.cursor` and `.cursor_context`. The `starpulse.board_feed` logger is now `starpulse.board.board_feed`. `python -m starpulse.mermaid_import` is `python -m starpulse.machine_engine.adapters.mermaid_import`.

| Old path | New path |
| --- | --- |
| `starpulse.adapter_kit` (the kit) | `starpulse.runtime.adapter_kit` |
| `starpulse.adapter_kit` (`WriteInstance`, `write_instance`) | `starpulse.runtime.write_instance` |
| `starpulse.board_feed` | `starpulse.board` |
| `starpulse.config` (`Config`, `ConfigError`, `load`, `runs_adapter`) | `starpulse.runtime.config` |
| `starpulse.config` (`CONFIG_OWNERS`, `restarts_serve`) | `starpulse.runtime.closure` |
| `starpulse.config` (`CommitKeys`) | `starpulse.board` |
| `starpulse.config` (`RunsInstance`) | `starpulse.runs` |
| `starpulse.conformance` | `starpulse.machine_engine` |
| `starpulse.machine_definition` | `starpulse.machine_engine` |
| `starpulse.mermaid_import` | `starpulse.machine_engine` |
| `starpulse.snapshot` | `starpulse.machine_engine` |
| `starpulse.history` | `starpulse.flow_metrics` |
| `starpulse.harnesses` | `starpulse.harness_telemetry` |
| `starpulse.otlp` | `starpulse.harness_telemetry` |
| `starpulse.claude_code`, `starpulse.cursor`, `starpulse.cursor_context` | `starpulse.runtime.claude_code`, `.cursor`, `.cursor_context` |
| `starpulse._internal.*` | not public; use the context packages above |

A package test pins this list and each module's names, so adding or removing one is a reviewed change.

## Board types

A task carries an optional `type`, a free string the board gives no meaning: `starpulse` ships no built-in names.
`[board] types` in the config file (the native board's `types` setting) is an optional list of the names it may take.
With the list declared, a write that sets a type outside it is refused with the list in the reason, whichever writer
makes it: `starpulse task create` and `task edit`, the page, `/api/tasks` and `/api/edit`; a task whose type is
unchanged is not refused, so narrowing the list never blocks an edit to a task already of another type. With no list,
any non-empty string lands. `starpulse board --type NAME` keeps only the tasks of that type, and each task the board
reports carries its `type` (empty when it has none). The Backlog.md adapter does not enforce the list.

## Board guards

`[[board.guards]]` in the config file (the native board's `guards` setting) declares record-level rules every task write
must satisfy, whichever writer makes it: `starpulse task move` and the other agent verbs, the page, and a workflow.
They are enforced where the native board lands a task file, so a move from the CLI and the same move from the page
meet the same rule and are refused with the same `reason` and `skill`, and nothing is written. The Backlog.md adapter
writes through the upstream CLI and does not enforce them. A board with no rules accepts every write it accepted
before, and a rule it cannot read (an unknown key or primitive, a missing `reason`, a bad pattern) is a startup error
naming `guards[N]`.

Release note: guards were `[[board.rules]]`. A config that still has that table is refused at startup with an error naming
`[[board.guards]]`; rename the table, nothing else changes. Every entry path is judged by the same enforcement point: the
config file's table, the task write verbs, the page, and `/api/tasks` and `/api/edit`. The Backlog.md adapter still
does not enforce guards, unchanged.

A rule is a table of:

| Key | Holds |
|---|---|
| `on` | which writes it judges: `{ to, from }` (a write that enters `to`, from one of `from` when given; either is a state name or a list), `{ to, from, while = true }` (also a write that leaves the task in a `to` state) or `{ write = true }` (every write, create and archive included) |
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
| `before` | `{ section = { heading = "Needs attention", not_matching = "\\?" } }`, any primitive | the task as it was before the write satisfies the nested primitive; a create had no earlier task, so it holds |
| `body` | `{ region = "description", matches = "AGENTS\\.md\\b" }` | the regular expression is found in the body, or in one region of it (`description`, `plan`, `acceptance_criteria`, `definition_of_done`, each between its `<!-- ...:BEGIN -->` and `:END -->` markers); an absent region holds nothing |
| `block` | `{ heading = "Start Criteria", key = "start_criteria" }` | the section under the `## ` heading holds a fenced `yaml` block that parses to a mapping whose `key` is a non-empty list; an absent section, fence or list fails |
| `readable` | `{ headings = [{ name = "Outcome", max_sentences = 1 }, { name = "Terms", optional = true }, { name = "Scope", no_paths = true }], commands = ["uv run", "git"], max_paths_per_sentence = 2, blast_radius = { heading = "Blast Radius", stops = "Stop Conditions", rollback = "Rollback" } }` | the description (the `DESCRIPTION` region, else the body) opens with its first `## ` heading and holds the `headings` in order, each required unless `optional`; in a section, a line starting with a `commands` prefix sits in a fenced block, the sentences number at most `max_sentences`, a `no_paths` section names no path, a path in prose sits in backticks, and no sentence names more than `max_paths_per_sentence` paths; the `blast_radius` section opens with `reach N · data N · undo N · detect N. <sentence>`, N 0 to 3, an axis at `stop_at` (default 3) or more is named in a `stops` section line, and `undo` at `rollback_at` (default 2) or more needs the `rollback` section. The refusal is the rule's `reason`, a colon and the first broken rule with its line in the description |
| `post_merge_checks` | `{}` | the body's `## Post-merge Checks` section is absent, or holds a fenced `yaml` block whose `post_merge_checks` list is valid (see Post-merge checks); a malformed check fails |
| `all_of`, `any_of`, `exactly_one`, `none_of` | a non-empty list of primitives | all, at least one, exactly one or none of them hold |

`readable` counts and prefix-matches; it judges no meaning. Its blind spots: a command outside the `commands` prefix list
passes; a path is a token with two or more slashes, a leading `/`, `.` or `~`, or a file extension, so `docs/specs` and
`and/or` pass; a sentence count cannot tell a summary from a second sentence; a well-formed `Blast Radius` with a wrong
score passes. Each board task also carries the rules' standing verdict as `readable` on its snapshot, feed and
`task show` record: empty when its description reads well (or the task is settled), else the first broken rule with
its line, so a page can badge a description written before the rules without refusing it until its next edit.

A write names its actor, which `unless_actor` matches. `POST /api/move`, `/api/edit`, `/api/archive`, `/api/verdict`, `/api/miss` and `/api/tasks`
take an optional `actor`, `session` and `harness`, each non-empty text (anything else is a 400). Every write parses its body through the request model of its route, so a body that is not a JSON object, names a key the route does not take or holds a field of the wrong type is a 400 `invalid request: <field>: <reason>` for its first fault. The page names
`operator`; `starpulse` verbs name `agent`, their session and their harness. A write naming no actor is `agent` when it
names a session and `anonymous` when it names none, never `operator`, so an unnamed write is not judged as the
operator's. The write's `board:lanes` row carries all three, and a create stamps `created_by: <harness>:<session>` in
the task (`anonymous` when it names no session). `POST /api/start` takes an optional `actor` and calls a board writer's
`assign` with it only when named.

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

`POST /api/verdict` `{task, check, verdict: "pass"|"miss"[, evidence, fix]}` records a check's verdict as a comment on
its task: `[post-merge-check] <id> PASS` or `MISS`, then `Fix: <task>` for a miss and the evidence. It answers 200
`{task, check, verdict[, fix]}`, 409 for a malformed block, an undeclared check or a check that already has a verdict (a
verdict is final), 400 for a `miss` that names no `fix` task, and 404 for a `fix` the board does not hold.
`POST /api/miss` `{task, check, fix: {title, ...as a create}[, evidence]}` files the fix task and records the MISS
verdict naming it in one call, answering 200 `{task, check, verdict, fix}`. When the verdict is refused after the fix
is filed, the fix is archived again, so a refused miss leaves neither. Both take the optional `actor`, `session` and
`harness` of every write.

## Versioning

StarPulse is versioned `0.y.z` until its interfaces settle: a minor version can break the config file, the adapter
contract or the command line, and a patch release never does. Each release is a
[GitHub Release](https://github.com/trantor-org/starpulse/releases) whose notes list the pull requests it contains.
