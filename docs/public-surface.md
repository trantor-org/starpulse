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
- The config file's keys, among them each `[[triggers]]` table's `on`, `start` and `when` ([Triggers](serving.md#triggers)),
  and the machine YAML with its JSON Schema (`machine.schema.json`).

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

## Versioning

StarPulse is versioned `0.y.z` until its interfaces settle: a minor version can break the config file, the adapter
contract or the command line, and a patch release never does. Each release is a
[GitHub Release](https://github.com/trantor-org/starpulse/releases) whose notes list the pull requests it contains.
