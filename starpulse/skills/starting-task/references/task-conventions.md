# Task Conventions

Rules for creating and editing a task on a StarPulse board through `starpulse task`. Never edit a
task file by hand: the board's guards judge a write, and a hand edit skips them. Column names
and the guards that gate a move are the project's own; read them with `starpulse task moves`.
Each project maps its repeatable steps (`start`, `test`, `check`, `deliver`, `pr-status`,
`finalize`) to commands with `starpulse command run NAME`; an unmapped step exits 4 and the
project's agent instructions name the fallback.

## Contents

- Command syntax
- Classification
- No resolution label
- Kind and size
- Free-form labels
- Execution-ready
- Structured fields
- Milestones (spec writing and slicing: [specs-and-slicing.md](specs-and-slicing.md))
- Duplicate checks at creation
- A Done task that needs more work
- Pausing: name the reason, `park` picks the lane
- Checks after the merge
- Validation: Start Criteria and check tasks

## Command syntax

The four task writes and the flags each takes; `--help` adds only `--server`, `--session` and
`--harness`, which come from the environment.

```bash
starpulse task create "<title>" --priority medium --type story --label kind-execute --label size-3 \
  --description "<text>" --ac "<criterion>" --dod "<item>" [--milestone m-<N>] \
  [--dependency PROJ-<N>] [--reference <url>] [--documentation doc-<N>] [--profile <profile>] [--status <lane>]
starpulse task edit PROJ-45 [--plan "<text>"] [--append-notes "<line>"] [--comment "<text>"] \
  [--ac "<criterion>"] [--reword-ac "2:<wording>"] [--remove-ac 3] [--check-ac 1] \
  [--dod "<item>"] [--check-dod 2] [--modified-file <path>] [--final-summary "<text>"]
starpulse task checkpoint-ac PROJ-45 2 "<command>: <result>"
starpulse task review PROJ-45 --ref <pr-url> --summary "<outcome>" --comment "<evidence>"
```

- A repeatable flag repeats once per value: `--label a --label b`, `--check-ac 1 --check-ac 2`.
- On `edit`, `--label`, `--dependency`, `--reference`, `--documentation` and `--modified-file`
  replace the whole list; `--ac`, `--dod` and `--append-notes` add; `--description`, `--plan`,
  `--notes` and `--final-summary` replace their section.
- `checkpoint-ac` takes no flags: the criterion's number, then one quoted evidence string.

## Classification

Every task declares a configured `priority` (`high`, `medium`, `low`) and `type`. They describe
the work, not its scheduling; `medium` only when the priority is genuinely unclassified.

A type is the task's output contract, orthogonal to its `kind-*` label. The board accepts only
the names the project's `starpulse.toml` declares, and enforces each contract as a
`[[board.guards]]` entry. A typical set:

| Type | Use when the task ships |
|---|---|
| `spike` | No pull request: a written conclusion (decision record, spec, current-state doc or learning note) and follow-up tasks; closes without `Review`. |
| `story` | A pull request that changes behavior, config or docs. |
| `bug` | A pull request that repairs a fault, with the test that reproduces it. |
| `chore` | A pull request that changes no behavior: a dependency bump, a rename, a cleanup. |
| `incident` | A live-state response; a pull request only when the fix is tracked state. |
| `check` | A validation verdict, before or after a merge; closes on a pass; a miss waits on its fix and measures again. |
| `retro` | No pull request: a milestone retro's verdict and the tasks it files. |

A `story`, `bug` or `chore` reaches `Review` only with its pull request recorded
(`starpulse task review TASK --ref <pr>`).

A spike's conclusion record is in scope even when the spike changes no tracked file: it has its
own Acceptance Criterion, and the task's documentation impact is never `none`. The record
describes the method in prose. A spike's scripts and harnesses are throwaway: they stay in a
scratch directory, are discarded with the spike, and are never checked in, kept in a board doc
or handed to a follow-up. So is any code a task runs only to get a number or a decision (a
measurement, study or eval): the number goes in its PR body or conclusion record, never its
code. A follow-up that needs the tool writes it fresh under its own tests.

## No resolution label

No label says who may resolve a task: every eligible `Ready` task is dispatchable, and one that
turns out to need the operator says so by reaching `Needs attention` with its reason (`park
--operator`, Pausing below). An assignee is always an agent profile, never a person: the
operator works any task by hand.

A decision-shaped task is still agent work: the agent researches it and leaves a decision
record with a recommendation prepared.

## Kind and size

Every task except an `unattended` one carries one kind label and one Fibonacci size label. The
rubric for each is in [sizing-and-assignment.md](sizing-and-assignment.md). A task that reaches
13 is split, never sized, except a mockup-interview task, which stays one size 8. A task the
operator works by hand keeps its profile: it is the model and effort to start that session with.

```bash
starpulse task create "<title>" --label kind-execute --label size-3 --priority medium --type story ...
starpulse task edit PROJ-91 --label kind-diagnose --label size-5
```

`task edit --label` takes the labels to set; remove the old kind or size in the same call so a
task never carries two.

## Free-form labels

A free-form label is kebab-case, at most three words and 24 characters, with no date, id or
hash: `follow-up`, not `weekly-code-audit-2026-10-25-follow-up`. The `kind-`, `size-`, `area-`,
`mode-` and `trial-` labels store first-class fields and are exempt. A scheduled caller's
idempotency key goes in the task's `source` field, never a label. A board may refuse a label
that breaks the rule; its refusal names the rule.

## Execution-ready

`execution-ready` says discovery and decomposition are complete enough to execute from the
brief; it buys no model and no extra attempt. A conforming task has six planning headings in its
Description (`Why This Matters`, `Current State`, `Scope`, `Constraints`, `Stop Conditions`,
`ADR Needed`), a non-empty Implementation Plan, and at least three Acceptance Criteria. A label
on sparse prose is a defect. Create roots as `Ready` and each slice with an unresolved
dependency as `Waiting` in the same call (`--status waiting --dependency PROJ-N`). Task creation
does not authorize execution.

## Structured fields

- **Acceptance Criteria** are the independently checkable Completion Gates: a named test, a
  drift check or another verifiable command, never a self-report. Lint is not a criterion: the
  `deliver` step lints the staged paths. Resolve a criterion command's executable on the host
  that runs it (`test -e <path>` or `command -v <tool>`); a tool that lives only in a container
  is written as `docker exec <container> <tool> ...`. A criterion over each listed item names
  every item in its command (one test path or `-k` per item), so a run on a subset cannot pass
  it. A `<claim>: <command>` criterion ends in the command, run as written, so write `! rg -q
  ...` or `test -z "$(...)"`, never trailing prose. Set them with repeated `--ac` on `starpulse
  task create` or `task edit`, and check each with `task edit --check-ac N` once its command has
  passed.
- **Definition of Done** is the project checklist plus a few task-specific outcomes; it does not
  repeat runnable commands, and it never waits on time after the merge (Checks after the merge).
- **Implementation Plan** is the ordered current route; revise it when discovery changes the
  route.
- **Implementation Notes** holds settled design decisions, rejected options and non-obvious
  constraints.
- **Comments** are the append-only checkpoint and finding log, one at each milestone.
- **Working doc** is the task's current state, linked as `documentation`: a board doc titled
  `PROJ-N working notes` (`starpulse doc create "PROJ-N working notes" --task PROJ-N`). It holds
  no durable fact: those go to a decision record or the project's docs before the task closes.
- **Modified Files** is set once at closure from `git diff --name-only <default>...<branch>`,
  never from a shared working-tree scan (`task edit --modified-file`).

## Milestones

A cohort of two or more delivery tasks belongs to a milestone; a single task never gets one.
Create the spec, then the milestone, then the tasks:

```bash
starpulse doc create "<plan title>" --folder specs --body "<approved plan>"
starpulse milestone add "<name>" --outcome "<finished when>" --spec doc-<N> --adr <path>
starpulse task create "<slice>" --milestone m-<N> ...
```

Move an existing task in with `task edit --milestone`. Correct a milestone with `milestone edit
m-<N>` (`--outcome`, or a `--spec` or `--adr` list that replaces the old one) and a spec with
`doc update doc-<N>`. A re-scope that replaces a spec decision the outcome names edits the
outcome in the same change, so the outcome never names a rejected design.

The milestone carries a retro task that waits on every task in the milestone, so it unblocks
when the cohort is `Done`. The retro summarises every task and finding, settles with the
operator whether the outcome and the spec's decisions are met, and files or declines what is
left; tasks it files do not gate it. Archive the milestone once the retro and the rest of its
cohort are `Done`.

**The retro also waits on every row of the spec's slicing table**, since a slice nobody cut is
in no one's dependencies. A task carries a row when its title equals the row's Title, or the row
cites its id in the Title cell or a cell left of it (`| T1c (PROJ-45) | <title> |`). Create a
slice under its row's Title; after retitling one, cite its id in the row; delete the row of a
slice the cohort dropped; when a row's verification moves onto another slice, cite that slice's
id in the row's Title cell, or delete the row, in the same step.

**An outcome that needs a soak window is a check task in the milestone.** When the milestone's
outcome can only be read after the cohort has run live for a while ("over the 7 days after the
last slice merges"), file a check task inside the milestone, created `Waiting` on Start Criteria
sized by the events the verdict needs, never elapsed time (Validation, below). The retro waits
for every task in its milestone, so it cannot open before the check closes. Whether an outcome
needs a soak window is the planner's judgement under the prove-now and judge-now rules.

Before writing a spec, slicing one into tasks or capturing a design interview, read
[specs-and-slicing.md](specs-and-slicing.md).

## Duplicate checks at creation

Before `task create`, run `starpulse search "<terms>"`. Each query expresses behavior or an
acceptance criterion from the requested work; paths and titles are search terms, never proof two
tasks share scope. Search matches every word as literal text, in title, description, criteria and
notes. A non-terminal hit with the same requested outcome is the duplicate: resume it or depend
on it, never create a replacement. Record the queries in the new task's Description.

## Issues found along the way

Any bug, regression or doc/code mismatch an agent discovers gets filed as a board task
immediately, deduplicated against existing tasks, and named in the report by id. Never only
described in a report. Filing a discovered bug is not scope creep; fixing it outside your task
is. The same holds for any issue an agent notices: a flaky or slow test, a doc mismatch, a
confusing guard, a stale task, a missing sanctioned path, tech debt it worked around. A context
that cannot file suggests the task in its report with a ready-to-file title and why.

Filing is not selecting: a filed task waits for the normal start path (the operator, autopilot,
or a standing rule), and no agent writes code, pushes or opens a pull request for it unselected.

## A Done task that needs more work

A finished task that needs more work gets a linked follow-up, not a reopen: create it with
`--reference PROJ-N` and a Description section `## Follows` naming `PROJ-N` and what it left
undone. The reference and the heading are a contract: never rename them. The follow-up carries
no native dependency on the finished task.

Reopen only a close that was itself wrong, such as one that landed on the wrong task, and
record why as a task comment.

## Pausing: name the reason, `park` picks the lane

An executor pauses its own `In Progress` task with `starpulse task park TASK` and exactly one
reason, never a lane. Paused work has two lanes, keyed on who releases it: `Waiting` (machine)
and `Needs attention` (human).

- `--until-task TASK-X` (repeatable) waits on another task. The IDs land in the task's
  dependencies and the task is `Waiting` until every one is `Done`, then promoted to `Ready`.
  `--until-task TASK-X#K` waits on one open criterion of `TASK-X` instead: the park records the
  need (`dependency_needs`), refuses a criterion that is absent or already checked, and the task
  actor releases the task once criterion K is checked, even while `TASK-X` stays open, with a
  `Stale dependency` comment. Park on the criterion or a `--until` fact when the need is a
  fact, not the whole task.
- `--until '<criterion yaml>'` (repeatable) waits on a condition a check can observe. It writes
  the task's Start Criteria and the task is `Waiting` until every criterion passes; see
  Validation below.
- `--operator '<reason>'` waits on an intervention only an operator can make, such as a
  credential, an irreversible action or an unresolved decision. `Needs attention` is exclusively
  a call to action for the operator: its reason names what the operator does or decides, and
  waiting for data, a run or time is never one, even when nothing observes it yet (Validation
  below). The lane and its reason are the whole signal; no label is written.

Add `--comment` for what is outstanding. A task filed to clear a parked task's `--operator`
blocker re-parks that task `--until-task` the fix in the same turn, so it leaves `Needs
attention` and the fix's `Done` releases it. A check task that measured a miss does the same:
it parks `--until-task` its fix (Validation, below).

A task whose pull request already merged is never parked, for any reason: it closes with
`starpulse task review`, which needs no deliver run then. A wait you can verify now, such as a
pull request's merge state, is verified, not parked. A task that never started and needs the
operator present, such as an interview, stays `Ready`; the session that claims it asks, and
parks `--operator` when the operator is not there to answer.

A `Waiting` task has either a dependency or Start Criteria, never both and never neither.
Creating a task with an unresolved dependency lands it `Waiting`, and starting it is refused
until every dependency is `Done`.

## Checks after the merge

A check after the merge never blocks the task that did the work. Its Acceptance Criteria and
Definition of Done are what the pull request shows before the merge, plus the initial QA the task
runs on itself, and each check after the merge goes in one of two buckets:

- **On merge.** A check the merge itself answers (the deploy applied, a pin moved, the merged
  commit's CI is green, a live endpoint answers after the apply) stays on the implementing task as
  a post-merge QA item: a criterion the task's QA plan names. Where the board's machine declares a
  post-merge QA phase in `Review`, that phase runs the items on the merge's own events (the
  merge, an apply finishing, a pin moving), never on a timer or a poll; a pass takes the task to
  `Done`.
- **Long wait.** A check that waits long on something else (a span of hours or days, a nightly, a
  scheduled run, a percentile over real traffic) is its own checkup task, `--type check`, filed
  at the moment the implementing task is created or delivered and parked
  `--until '<criterion>'` on an observable: the value the check reads, a run, or a lane move
  (Validation, below). Never a clock: a gate that compares the time against a deadline is a
  poll, and it opens whether or not the evidence exists. No window shortens this: a check due
  within 24 hours of the merge is a checkup task too, never a Definition of Done item on the
  implementing task.

A check that waits on a deploy (the merge landed, the live release has not applied it) parks once,
`--until release_contains:<merge sha>`: met when the live release checkout holds a commit
descending from that sha, so it wakes on the deploy and never re-parks to re-check. Do not park
`--until-task` or re-park on a timer for it.

A mechanism claim is proved before `Review` instead (Prove now, below). A check that needs
operator approval to run, such as a load burst against a live service, or a person's judgement,
such as a render on a device, is proved before `Review` or run with the operator.

For example, a task that cuts a DAG's run time from 150 s to 33 s locally shows the cut in its
pull request (a benchmark, a test), and "the merged commit's deploy applied" is its post-merge QA
item. "p50 under 30 s over the 24 h after the merge" is a separate checkup task: `--type check`,
its criterion that sentence, and a Start Criterion on the value the check reads, the DAG's runs
since the merge, such as `{id: runs-since-merge, kind: prom, expr: 'sum(increase(<the DAG's run
counter>[24h]))', at_least: 24}`. It opens once that many runs exist, not when a date passes. A
miss on that checkup files a fix task; it never reopens the implementing one.

A check whose criterion names a time window (`24h`, `3 days`) takes a start criterion that observes
data past the window end, never the merge alone: a `file_changed_since` or `pr_merged` start opens the
check at the merge, hours before the window's data exists, and the session then idles `In Progress`
or asks the operator to wait. Look for a series or table whose samples cover the window end (a
metric's `updated_timestamp_seconds` gauge, a table's newest row) and gate on it, for example
`{id: window-closed, kind: prom, expr: 'max(<exporter>_updated_timestamp_seconds)', at_least: <merge
+ window epoch>}`. The task lint refuses a check whose Acceptance Criterion names an hour or day
window while every Start Criterion is `file_changed_since` or `pr_merged`; a data kind beside the
merge one clears it. A session on an unattended check never parks `--operator` for such a wait: it
parks `--until` the data kind.

A check's gate must not be the live effect it checks, or a missing effect reads as waiting
forever. A live check drives the actor along its ordinary path and never supplies by hand the
key that path derives: a criterion that passes only because the skill args named the task proves
nothing.

A metric criterion over a counter or a histogram's `_count` reads `increase(<series>[<window>])`,
never the raw series: a process restart resets a counter to zero, so the raw value can read 0
though the change ran.

## Validation: Start Criteria and check tasks

Start Criteria hold a wait, such as a validation pair gating work that has not started, a parked
task, or a check task on a delivery's post-merge evidence. A task carrying Start Criteria, or
the `validation` label (a task whose whole purpose is the check), waits in `Waiting` until every
criterion passes; the board's task actor moves it to `Ready` then, and back to `Waiting` if a
criterion stops passing, and autopilot claims only from `Ready` after re-checking the criteria.
A task whose wait is a condition ("after a week of data", "once the next release lands") states
it as a criterion rather than prose, which no reader evaluates.

**One gate per task: native dependencies or Start Criteria, never both.** Start Criteria are
for a wait no task expresses, and a criterion that measures an event already implies what
precedes it, so that task drops the dependency.

A validation pair is a `Waiting`, `validation`-labelled task carrying the criteria, plus the
requested task depending on it; the requested task lands `Waiting` and is promoted to `Ready`
once the validator reaches `Done`.

**Prove now what can be proved now; wait only for what must accumulate.** Before filing a check
task or parking a task behind Start Criteria, sort each claim by what it claims:

- A mechanism claim (the code prunes, archives, routes, filters, debounces, deploys or fires on
  an input) is proved now, never by waiting for that input to arrive live, and is never declared
  or parked: its delivery task proves it before `Review`, or it runs now. Prefer an integration
  test seeded with the project's model factories on an ephemeral database, which reproduces and
  keeps guarding; otherwise replay existing history through the new logic, feed synthetic input,
  or run the real path by hand (a manual job start, a dispatched CI job, one API call).
- An accumulated-outcome claim (a rate, share or percentile over real traffic, a statistical
  sample, a soak under real load, work only a person does) may wait, but only after its query has
  run on the data that exists. Size the window to the smallest sample that answers it, and say
  in the check's criterion or description why no faster route does, with the arithmetic: the
  expected exposures per day and the count the verdict needs. A round "7 days" or "14 days" with
  no such count is the calendar. A soak is required only when the mechanism under check runs on
  a timer, and its window is sized by exposures, the events that can trigger the fault (a live
  upgrade, a sibling migration merge), never by run count: 500 runs over two days with no
  trigger event is no evidence for a fault that fires about once in ten days. The window counts
  from a fixed instant, such as the merge's apply instant, never from a process start a redeploy
  resets.

**Judge now; wait only while the data is undecided.** Before parking a task, and again whenever a
check task is claimed, run its own query on the data so far; it closes on that verdict when the
verdict is already decided.

- A miss is decided the moment one counter-example exists: a peak over the bound, a failed run, a
  non-zero error count. A window can only add misses.
- A pass is decided when the margin is one the rest of the window cannot reverse: a peak that
  fell from 400-800 to under 100 across a full weekday cycle, a share already past its bound with
  enough samples that the remaining ones cannot move it back.
- For a parked task, a wait for the next scheduled run of a job, timer or workflow is a manual
  run now, unless the schedule itself is what changed.

Worked example: a check task that a host's weekday load peaks fall below 150 after a fix,
against a baseline of 396-839, queries the peaks since the merge first. One weekday peak over
150 is a miss now; one full weekday under 150 against that baseline is the verdict, not a reason
to wait 14 days. Only a check whose data does not exist yet parks, on the event that creates it,
such as `--until '{id: peak-day, kind: prom, expr: "max_over_time(node_load1[1d])", at_most:
150}'` with a comment naming the query and the baseline.

**A check that needs N samples parks once on their count.** Count the samples the verdict needs
from the window's fixed start, gate on that count, and claim the check once with every sample
present. Never park on the next single run, wake, take one sample and park again: each sample then
costs a release, a claim and a park. Worked example: a check that three merge-queue CI runs after
an apply start their shards within 12 s, with one run in so far, parks once on `--until '{id:
three-ci-runs, kind: dagu_run, dag: ci, since: "<apply instant>", at_least: 3}'`, not on the next
run. Any count kind serves the same way, such as a SQL or metric query's `at_least: N`.

**After two consecutive misses on the same duration or latency Outcome target where
a diagnosis has already named a path floor, the next slice is `kind-decide` (architecture change
or Outcome revise), never another fix/check pair that re-measures the same target.**

Never gate on an incidental event, such as an unrelated commit touching a path, when a deliberate
trigger exists: a live retention prune that a seeded test or one manual timer run shows the day
it merges needs no 23-day wait.

A criterion's `kind` is one of the closed set the board's configuration supports (typically a
SQL or metric query compared against `at_least`, `at_most` or `equals`, a log-metric query, a
workflow-run status, and git kinds for a path changed or unchanged since a date, or a submodule
pin reaching a commit). The project's park and create commands list the exact kind names in their
`--help`; a wait on a merge is the git path-changed kind on a path the change touches, `since`
the instant the wait began. A date-only `since` counts from 00:00 UTC; an ISO-8601 timestamp counts
from that instant, so a wait on a path already touched that day sets it to the time the wait
began.

**Measure the awaited data, never the calendar.** There is no date kind: a wait is always on
something that lands, and the criterion observes it.

- A merge touching a path is a path-changed criterion on that path, including another
  repository's merge synced in, such as a dependency bump or a lock file.
- An upstream commit reaching a submodule pin is a pin-contains criterion on the submodule path
  and that commit, since a bump without it still touches the path.
- Live state (a scheduled run's output, a metric, a board row) is a query criterion.
- A window of data gates on the value the verdict reads, not on how much of it exists:
  `max_over_time`, `changes` or `increase` of the series, or a count of the events (runs, merges,
  sessions) the verdict needs. Counting scrape samples is elapsed time, and a query that reads no
  series (`time()`) or no table is the calendar under another name.
- `absent(m{l="v"})` carries the labels `{l="v"}`, so `x * absent(m{l="v"})` (or `and`, `unless`,
  `+`) matches nothing; write `x * on() absent(m{l="v"})`.

**Write a known wait as the create's gate, on the event the check reads.** A task whose own text
says when it can run ("after the first scheduled run", "once five PRs have opened", "14 days
after the merge") is created `Waiting` with that criterion, never `Ready` with "park with
`--until` if earlier" prose: its first claim would only park it. Gate on what the task reads, not
on an event before it. A criterion that already passes waits for nothing, so give a path-changed
criterion a `since` after the last commit that must not count.

A check task on a scheduled applier gates on the run: a row, metric or step output only the
deployed step writes, never the merge or the schedule's trigger, unless the schedule itself
changed.

When no kind observes the awaited condition, make it observable: create a delivery task that
publishes the condition as a metric or a table row, then follow the check-task table below. A
metric series that does not exist yet does not pass, so the criterion can name it before the
delivery merges. Example: a check waiting for 50 rows in a local JSONL ledger gets a task
exporting the row count as a gauge, and its criterion is
`{id: rows-50, kind: prom, expr: <gauge>, at_least: 50}`.

**Start Criteria gate only autopilot's claim.** An explicit operator start claims the task
(`starpulse task claim`) whatever its criteria say. Whoever works it checks the real condition
live and closes the task when it holds. No automated evaluator closes one.

**A check task closes on a pass and waits on the fix of a miss.** A check task is one typed
`check`; a task labelled `validation` must be. When it measures its
criterion, it records the verdict with `starpulse task verdict TASK CHECK pass` or
`miss --evidence ... --fix PROJ-M`. A pass closes it; a miss parks it on its fix, whose `Done`
returns it to `Ready` to measure again:

- A miss records what it measured and forks the fix as its own task. The miss quotes the failing
  unit's or step's own error line, from its journal or job log, and names a cause only from that
  line, never from a fault seen nearby.
- The fix files no second check for the same criterion: the parked check measures it.
- A fix task that declines its change re-scopes or archives the check waiting on it in the same
  step; left waiting, that check never releases.
- When the criterion passed without the condition holding, tighten it before parking.

A check task looks up its next command in this table, taking the first row that matches; it never
chooses one. This table is the whole park rule for a check task.

| Verdict | Command |
| --- | --- |
| Every criterion checked | the project's `finalize` step |
| Miss, no fix task filed | `starpulse task create` the fix, then the next row |
| Miss, fix PROJ-M filed | `starpulse task park PROJ-45 --until-task PROJ-M --comment '<miss>'` |
| Threshold a prior diagnosis showed unreachable on its path | `starpulse task park PROJ-45 --operator '<threshold decision>'` |
| Data not landed, a kind observes it | `starpulse task park PROJ-45 --until '<criterion>' --comment '<query>'` |
| Data not landed, no kind observes it | create the task that publishes it (above), then the previous row |
| Waits on another task | `starpulse task park PROJ-45 --until-task PROJ-46#K`, the criterion the wait needs |
| Only a person can act: a credential, an irreversible action, a decision | `starpulse task park PROJ-45 --operator '<what they do>'` |

A park on a check task, by any task, names the check's criterion (`--until-task PROJ-46#K`) or
the run or data it observes (`--until`), never the check's `Done`: that waits on every criterion
of the check, so one late criterion holds each task parked behind it.

A miss never parks `--operator`: the fix's `Done` releases the check, and a person is needed
only when a row above names one. A wait for data, a run or time is never `--operator`.
