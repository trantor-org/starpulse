# Compatibility

## Public surface

What a release keeps compatible; a minor `0.y` release may break it, and its notes say so. Everything else in the package is
internal and can change in any release.

- The `starpulse` command line: its verbs, their JSON output and their exit codes ([each verb](cli.md)). The task write
  verbs are `task create TITLE [--description --priority --milestone --profile --status --type --label --dependency --ac
  --reference --documentation --dod]`, which
  returns `{task}`; `task edit TASK [--title --type --priority --milestone --label --dependency --reference
  --documentation --modified-file --description --plan --notes --append-notes --final-summary --ac --reword-ac
  --remove-ac --check-ac --uncheck-ac --dod --reword-dod --remove-dod --check-dod --uncheck-dod --comment --base]`,
  which returns
  `{task, changed}` and is refused whole (exit 1) when a field it changes is stale against its base;
  `task profile TASK PROFILE`, which returns `{task, profile, changed}`; `task archive TASK [--reason]`, which returns
  `{task}`; `task verdict TASK CHECK pass|miss`, which returns `{task, check, verdict}`, and `task miss TASK CHECK --title`,
  which returns `{task, check, verdict, fix}`, each refused (exit 1) for a check that is undeclared or already judged; `task restore TASK`, which returns `{task}` and is refused (exit 1) for a task that is open, not archived or
  whose file name is taken; `task retire TASK`, which returns `{task}` and is refused (exit 1) for a task that is open;
  `task retired [TASK]`, which returns `{tasks}`, each `{task, name, text}`; `task import-retired FILE...`, which returns
  `{tasks}`, the imported ids; `task complete TASK`, which returns `{task}` and is refused (exit 1) for a task that is not Done;
  `task claim TASK`, `task park TASK` and `task review TASK`, which return `{ok, task, to, assignee, reason, skill}` ([cli](cli.md)) and are refused (exit 1) with the reason and skill of the guard or rule that judged them; and
  `task checkpoint-ac TASK CRITERION EVIDENCE`, which returns `{task, criterion, changed}` and is refused (exit 1) for a
  criterion the task lacks. Each exits 0 on success, 1 refused, 2 usage, 3 when the board cannot write tasks and, for
  every verb but `create`, 4 for an unknown task.
- `starpulse import-history`, and the JSON Lines it reads: one `{event_id, task, lane, time}` object per line ([format](cli.md#importing-a-boards-history)).
- The documented entry point `python -m starpulse.claude_code`, which receives Claude Code's and Codex's OTLP log
  exports, `python -m starpulse.cursor`, which reads Cursor's agent transcripts, and `python -m starpulse.cursor_context`,
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
  (see [Connect sources](sources.md#find-missed-skill-loads-and-recurring-work)).
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
  `completion_skill`, `completion_call`, the optional `[analytics.labeller]` table's `url`, `model`, `instructions`,
  `criteria` and `timeout`, each `[[analytics.skill_loads]]`'s
  `skill`, `activities`, `title` and `label`, and each `[[analytics.skill_machines]]`'s `skill` and `stages` (`name`,
  `activities`, `ok`), and the `[search]` table's optional `embeddings_url`, `model` and
  `token_env` ([Config file](serving.md#config-file)),
  and the machine YAML with its JSON Schema (`machine.schema.json`).
- A machine state's optional `waits` key: a map from a fact kind (`pr_terminal`, `deps_done`, `deps_unresolved`,
  `criteria_met` or `criteria_unmet`) to the event that leaves the state when that fact holds. The loader refuses an
  unknown fact kind and an event that is not a transition out of the declaring state, naming the state and event, and
  exposes the declared map as `Compiled.waits` (`{state id: {fact kind: event}}`; a child flow's states carry their
  `<state>_<child state>` id). Declaring `waits` fires nothing by itself: a board adapter hands the Board machine's map
to the server as `Board.waits`, and the task actor (`[board.actor]`, [Task actor](serving.md#task-actor)) fires the event
when the fact holds; `Board.holds` withholds `deps_done` with reasons. The actor's series on `GET /metrics` are
`starpulse_task_actor_refusals_total`, `starpulse_task_actor_latency_seconds`, `starpulse_task_actor_projection_seconds`,
`starpulse_task_actor_handoff_seconds`, `starpulse_task_actor_criteria_errors` and `starpulse_task_actor_pin_held`.
`starpulse_board_lane_unattributed_total` counts the `board:lanes` entries appended since `serve` started that name no actor.

The modules an adapter may import, each exporting exactly the names in its `__all__`:

- `starpulse.board`: the board adapter seam (`Board`, `Written`, the writer, task, milestone and doc protocols, and the `UpstreamBacklog` reference adapter).
- `starpulse.board_feed`: the feed a board adapter places tasks on (`BoardFeed`) and what following a stream needs of it.
- `starpulse.contracts`: the board (a `BoardTask` carries `acceptance_criteria` with `acceptance_checked`, `pause_reason` and `notes` beside its `description`), machine-event, run-event (`RunEvent`), lane-event (`LaneEvent`), runs (`Dag`, `RecentRun`) and insights (`Finding`) records, their JSON Schemas, `EVENT_STREAMS` (the record of each event log stream), and `RunsSink`.
- `starpulse.adapter_kit`: the test kit an adapter or insights engine author runs against their work, and the helpers that serve it.
- `starpulse.machine_definition`: loading and validating a machine, and the `Registry` of guards and actions.
- `starpulse.snapshot`: how a machine is described to the page, and how its workflows are named.
- `starpulse.history`: the history a board adapter may keep itself, and placing a task's events on a machine.
- `starpulse.event_log`: the database event log producers append to and readers tail; [Build a consumer](consumers.md) shows a reader that keeps its cursor in its own store.
- `starpulse.config`: loading the config file, the runs adapter a `type` names, and `CONFIG_OWNERS` (the processes that read each key) with `restarts_serve` (whether a change to the raw tables needs `serve` itself restarted).
- `starpulse.harnesses`: loading the harness file, the tiers and efforts an agent profile names.
- `starpulse.conformance`: replaying recorded moves (`check_lanes`, `check_events`) and event traces (`conform`, `replay`, `runs`) against a declared machine, and the paths and gate `bypasses` a machine generates.
- `starpulse.diagram`: `machine_dot(base)`, the Graphviz DOT of each machine under a project's `.starpulse/machines/`, as `machine show --format dot` prints it, with no server.
- `starpulse.mermaid_import`: drafting a machine definition from a Mermaid state diagram.
- `starpulse.otlp`: decoding Claude Code's OpenTelemetry log export.

A package test pins this list and each module's names, so adding or removing one is a reviewed change.

## Board types

A task carries an optional `type`, a free string the board gives no meaning: `starpulse` ships no built-in names.
`[board] types` in the config file (the native board's `types` setting) is an optional list of the names it may take.
With the list declared, a write that sets a type outside it is refused with the list in the reason, whichever writer
makes it: `starpulse task create` and `task edit`, the page, `/api/tasks` and `/api/edit`; a task whose type is
unchanged is not refused, so narrowing the list never blocks an edit to a task already of another type. With no list,
any non-empty string lands. `starpulse board --type NAME` keeps only the tasks of that type, and each task the board
reports carries its `type` (empty when it has none). The Backlog.md adapter does not enforce the list.

## Board rules

`[[board.rules]]` in the config file (the native board's `rules` setting) declares record-level rules every task write
must satisfy, whichever writer makes it: `starpulse task move` and the other agent verbs, the page, and a workflow.
They are enforced where the native board lands a task file, so a move from the CLI and the same move from the page
meet the same rule and are refused with the same `reason` and `skill`, and nothing is written. The Backlog.md adapter
writes through the upstream CLI and does not enforce them. A board with no rules accepts every write it accepted
before, and a rule it cannot read (an unknown key or primitive, a missing `reason`, a bad pattern) is a startup error
naming `rules[N]`.

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
| `body` | `{ region = "description", matches = "AGENTS\\.md\\b" }` | the regular expression is found in the body, or in one region of it (`description`, `plan`, `acceptance_criteria`, `definition_of_done`, each between its `<!-- ...:BEGIN -->` and `:END -->` markers); an absent region holds nothing |
| `block` | `{ heading = "Start Criteria", key = "start_criteria" }` | the section under the `## ` heading holds a fenced `yaml` block that parses to a mapping whose `key` is a non-empty list; an absent section, fence or list fails |
| `post_merge_checks` | `{}` | the body's `## Post-merge Checks` section is absent, or holds a fenced `yaml` block whose `post_merge_checks` list is valid (see Post-merge checks); a malformed check fails |
| `all_of`, `any_of`, `exactly_one`, `none_of` | a non-empty list of primitives | all, at least one, exactly one or none of them hold |

A write names its actor, which `unless_actor` matches. `POST /api/move`, `/api/edit`, `/api/archive`, `/api/verdict`, `/api/miss` and `/api/tasks`
take an optional `actor`, `session` and `harness`, each non-empty text (anything else is a 400). The page names
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
