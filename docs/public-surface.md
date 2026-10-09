# Compatibility

## Public surface

What a release keeps compatible; a minor `0.y` release may break it, and its notes say so. Everything else in the package is
internal and can change in any release.

- The `starpulse` command line: its verbs, their JSON output and their exit codes ([each verb](cli.md)). The task write
  verbs are `task create TITLE [--description --priority --milestone --assignee --label --dependency --ac]`, which
  returns `{task}`; `task edit TASK [--title --type --priority --milestone --label --dependency --reference
  --documentation --modified-file --description --plan --notes --final-summary --comment --base]`, which returns
  `{task, changed}` and is refused whole (exit 1) when a field it changes is stale against its base; and
  `task assign TASK ASSIGNEE`, which returns `{task, assignee, changed}`. Each exits 0 on success, 1 refused, 2 usage,
  3 when the board cannot write tasks and, for `edit` and `assign`, 4 for an unknown task.
- The documented entry point `python -m starpulse.claude_code`.
- The config file's keys and the machine YAML with its JSON Schema (`machine.schema.json`).

The modules an adapter may import, each exporting exactly the names in its `__all__`:

- `starpulse.board`: the board adapter seam (`Board`, `Written`, the writer, task, milestone and doc protocols, and the `UpstreamBacklog` reference adapter).
- `starpulse.board_feed`: the feed a board adapter places tasks on (`BoardFeed`) and what following a stream needs of it.
- `starpulse.contracts`: the board, machine-event, run-event (`RunEvent`), lane-event (`LaneEvent`), runs (`Dag`, `RecentRun`) and insights (`Finding`) records, their JSON Schemas, `EVENT_STREAMS` (the record of each event log stream), and `RunsSink`.
- `starpulse.adapter_kit`: the test kit an adapter or insights engine author runs against their work, and the helpers that serve it.
- `starpulse.machine_definition`: loading and validating a machine, and the `Registry` of guards and actions.
- `starpulse.snapshot`: how a machine is described to the page, and how its workflows are named.
- `starpulse.history`: the history a board adapter may keep itself, and placing a task's events on a machine.
- `starpulse.event_log`: the database event log producers append to and readers tail; [Build a consumer](consumers.md) shows a reader that keeps its cursor in its own store.
- `starpulse.config`: loading the config file, and the runs adapter a `type` names.
- `starpulse.harnesses`: loading the harness file, the tiers and efforts an agent profile names.
- `starpulse.mermaid_import`: drafting a machine definition from a Mermaid state diagram.
- `starpulse.otlp`: decoding Claude Code's OpenTelemetry log export.

A package test pins this list and each module's names, so adding or removing one is a reviewed change.

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

A primitive is a one-key table naming its kind (`require = { label = { contains = "needs-human" } }`); the table gives
the value under that key:

| Primitive | Value under the key | Holds when |
|---|---|---|
| `field` | `{ field = "references", matches = "/pull/\\d+$", in = [...], min = 1 }` | a scalar or list front matter field has at least `min` (default 1) items that match the pattern and are in the set; one of `matches`, `in` or `min` is required |
| `label` | `{ contains = "needs-human" }` or `{ prefix = "size-", in = [1, 2, 3, 5, 8] }` | the task has the label, or has a label with the prefix and every such label is the prefix and a value of `in` |
| `section` | `{ heading = "Needs attention", nonempty = true }` or `{ heading = "Needs attention", not_matching = "\\bTASK-\\d+\\b", except_self = true }` | the body has a `## <heading>` section (up to the next `##`); with `nonempty` it is not blank; with `not_matching` its text, an absent section's counting as empty, does not match, `except_self` first dropping the task's own id |
| `dependencies` | `{ all_in = ["Done"] }` | every task in `dependencies` is in one of the named states; a dependency with no task file is in none, and no dependencies holds |
| `checklist` | `{ sections = ["acceptance_criteria", "definition_of_done"], all_checked = true }` | every item of the named lists is checked; an empty or absent list holds |
| `all_of`, `any_of`, `exactly_one`, `none_of` | a non-empty list of primitives | all, at least one, exactly one or none of them hold |

A write names its actor, which `unless_actor` matches. `POST /api/move` takes `actor` (`operator` when absent, which is what
the page sends; `starpulse task move` sends `agent`). `POST /api/edit`, `/api/archive`, `/api/tasks` and `/api/start`
take an optional `actor` the same way: a board writer's `edit`, `archive`, `create` and `assign` receive it as the
`actor` keyword only when the request named one, so a writer that predates actors keeps working, and a name that is
not non-empty text is a 400.

## Versioning

StarPulse is versioned `0.y.z` until its interfaces settle: a minor version can break the config file, the adapter
contract or the command line, and a patch release never does. Each release is a
[GitHub Release](https://github.com/trantor-org/starpulse/releases) whose notes list the pull requests it contains.
