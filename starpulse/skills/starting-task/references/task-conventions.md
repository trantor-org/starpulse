# Task Conventions

Rules for creating and editing a task on a StarPulse board through `starpulse task`. Never edit a
task file by hand: the board's guards judge a write, and a hand edit skips them. Column names
and the guards that gate a move are the project's own; read them with `starpulse task moves`.
Each project maps its repeatable steps (`start`, `test`, `check`, `deliver`, `pr-status`,
`finalize`) to commands with `starpulse command run NAME`; an unmapped step exits 4 and the
project's agent instructions name the fallback.

## Contents

- Classification
- No resolution label
- Kind and size
- Execution-ready
- Structured fields
- Milestones: Writing the spec, Slicing a spec, Capturing a design interview
- Duplicate checks at creation
- A Done task that needs more work
- Pausing: name the reason, `park` picks the lane
- Evidence only the merge produces
- Validation: Start Criteria and check tasks

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
| `check` | A validation verdict, before or after a merge; closes on its first verdict. |
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
  repeat runnable commands.
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

### Writing the spec

A spec has an Outcome, one section per decision (each with a Measure line), Exclusions and a
slicing table with `Title`, `Kind`, `Size` and `Profile` columns. These rules keep a spec from
passing its own measure while missing the outcome; they are wording, not a pre-merge check, and
a gap they miss is what the retro is for:

- **Name the blind spot.** Each decision's measure states what it cannot see and the negative
  case it must detect: the input on which the outcome fails and the measure still reads green.
  The slice delivering that decision, or its check task, carries a criterion that drives the
  negative case.
- **Name every entry path.** A decision's measure names every path by which an item enters the
  set it measures (each route, trigger or caller), and a slice that adds a path updates the
  measure. "Every actionable verdict posts" missed an overnight route added a day later.
- **Classify before remedying noise.** A remedy for alert or investigation noise (a debounce, a
  threshold, a filter) follows a classification of why the no-op runs end as no-ops, and the
  spec cites it. A debounce chosen first can hide real failures.
- **Name the runner.** An outcome word that implies something runs it (recurring, weekly,
  alerting, nightly) gets an Acceptance Criterion naming the scheduler or job that runs it;
  without one the word describes an intent nothing executes.
- **Research before tuning adoption.** A plan whose problem is that agents skip a tool, miss
  guidance or fail to trigger a skill opens with a research step (why agents skip such a tool,
  how guidance triggers); tuning by trial (a stronger description, another routing row, a louder
  instruction) starts only from what it found, and the spec cites it or says why the step was
  skipped.
- **Time one real run before fixing a latency budget.** A decision that sets a latency budget
  times one real run of the proposed path, including its fixed start overhead, before it fixes
  the number. A budget pinned from a script dry run missed the real job-start median and took
  four more tasks to reach.

### Slicing a spec

Read the whole spec before creating the first slice:

- **Every Outcome clause maps to a decision, slice or Exclusion.** Pair each clause of the
  spec's Outcome with the decision or slice that delivers it, or an Exclusion that drops it.
- **Every promised effect has a slice that owns it.** Each effect a decision promises (applies,
  rewrites, honours, opens) maps to a named slice whose criteria produce it, and every existing
  producer that must respect a new decision kind is named in a slice. An effect no slice owns
  stays manual, and an unnamed producer undoes it.
- **A restricted set's inventory is a command's output.** When a decision restricts or moves a
  set (imports, call sites, files), the spec's Today inventory quotes the command that lists it
  beside its output, never a count from reading.
- **A numeric budget on a named host quotes a floor from that host.** The spec's Today section
  quotes one run on that host showing the budget is reachable there (an idle or empty-page
  floor).
- **A slice that moves or removes a path another repository imports orders that repository's
  adoption first.** The consumer's change, passing against both the old and the new layout,
  merges before the change that removes the old one. The same holds for a dependency group,
  extra or CLI flag it removes or renames: grep the consumer for its name and cut the consumer's
  slice first as the other slice's dependency.
- **A slice that removes live state ships its tracked apply path.** Its criteria name the
  declaration and the unattended apply that removes the state, never a hand-step list in the PR
  body.
- **A slice that changes a field's meaning ships its readers' change with it.** Either the same
  slice updates every reader, or it keeps the old meaning until the reader slice lands. No check
  names a meaning change, so the slicer must.
- **A slice whose check or decision reads a measurement depends on the slice that feeds it.**
  Give it a native dependency on the slice that produces the measurement, so it cannot merge
  first.
- **A deferred slice has an owner, not only a prose promise.** File it as a task at `Waiting`
  with a native dependency on the predecessor that makes it actionable, a deferred deletion
  included. A deferred step left only in the spec never enters the queue when its prerequisite
  closes.
- **Serial slices merge, then every slice is filed up front.** First merge serial slices that
  touch one module into fewer, larger slices. Then create every remaining slice at `Waiting`
  with a native dependency on its predecessor, so dispatch ordering sees the whole chain.
- **A layout spec shows a before/after path.** A spec that changes a directory or package layout
  shows, in its Outcome, one concrete before/after path for one member.
- **A spec that defers a candidate to another group names its owner.** The task or milestone
  that owns the candidate is written beside it; a group label alone leaves it unowned.
- **A slice that produces a decision list names its receiver and route.** Its criteria say who
  decides each item and the path the list reaches them by (a review task, a question in a reply,
  a dashboard they already read).
- **A measurement spec asks what its ratings mean.** Ask the operator whether they are a
  baseline or a ceiling and which candidates are in scope before slicing. Fix no use case or
  constraint the operator did not ask for.
- **A clause conditional on an operator fact is a question, not a default.** A clause shaped "X
  stays if the operator uses Y" or "drop Z unless W" is asked of the operator before slicing,
  and the answer is recorded in the spec. When the operator is not available to answer, the
  clause becomes an Acceptance Criterion on the slice that owns X, worded so the slice cannot
  reach `Review` while the fact is unresolved.
- **Every spec decision's Measure line is run by a criterion,** except an invariant whose own
  check is the outcome: the delivering slice's, or a check task's when only the merge produces
  the data. The criterion runs the Measure line itself: the outcome, not that the mechanism
  ran. Each Measure line is its own criterion, so no named line goes unrun.
- **A decision whose Measure is only unit tests names its production caller.** The slice
  delivering it names the caller that runs the code in production, and a criterion proves that
  caller exists (a call-graph query listing a non-test caller). A retention decision measured
  only by unit tests can ship a prune function nothing calls.
- **A slice cites the accepted decision record its subject already has.** Before slicing,
  search the decision records for each slice's subject and cite every accepted one the slice
  must follow in its description.
- **A slice that cuts over live state gets its check task at slicing time.** Retiring a unit,
  moving a port or bind, or swapping a service is a cutover: create beside the slice a check
  task, `Waiting` on Start Criteria that observe the merged change, whose criteria show the
  service answering after the merge applies (Validation, below). The slice's Acceptance
  Criteria stay pre-merge gates, which cannot see an outage that merging introduces.
- **A migration of live data outside the PR is a cutover too.** A slice that rewrites files the
  PR does not carry gets a check task that reads the migrated data after the merge applies; its
  contract slice (legacy-reader removal) is created with the cohort and depends on that check
  task.
- **A slice that deletes a required CI job gets an earlier ruleset-only slice.** That slice
  drops the job's required check from the branch rules alone, and the deleting slice depends on
  it: a PR that deletes the job and its requirement together waits on a required check that
  never reports.
- **A hand-run apply step is named, and its check waits for it.** When a slice's change goes
  live only after a step someone runs by hand after the merge (registering a runner, rebuilding
  an image the push does not build), the slice names that step, and its check task's Start
  Criteria confirm the apply through something they can observe (a runner count, the image's
  created time), so the check measures only after it.
- **A check of an idempotent apply path names the branch it observes.** When the ordinary path
  can pass by changing nothing, the check names which branch it expects, a no-op pass or an
  applied change, and its Start Criteria observe that same branch.
- **A migration's one-shot cutover steps are deleted, and absence is proved over the whole
  repository.** The removal or data-move code that ran once is deleted by a task depending on
  the cutover's check task, not kept as a "deliberate mention". That task's absence criterion
  greps the whole repository with hidden files (`rg --hidden -n '<term>'`), never a list of
  subtrees.
- **A slice whose live gate reads state a sibling's merge changes depends on that sibling.**
  The typical case is a detector on its fix: give the detector slice a native dependency on the
  fix slice, so the gate passes because the fix applied rather than because the state was
  repaired by hand.
- **Sibling slices that write the same module or helper do not run in parallel.** Give the later
  slice a native dependency on the earlier one, or let the first own the shared helper and the
  rest depend on it; slices on disjoint files stay parallel.
- **A dashboard rebuild or push is a cutover too.** Its check task reads the live dashboard, not
  the builder: panels that overlap, titles and windows that disagree with the time picker, and
  panels a sibling dashboard already shows.
- **Moving CI jobs between shared runner lanes is a cutover too,** as is any change to shared CI
  capacity. Its check task measures the queue p90 of every lane the move touches, the lane
  gaining jobs as well as the one losing them.
- **A spec with UI work gets an approved mockup before its first slice.** When any slice would
  change what a page or dashboard draws, lays out or animates, the operator approves a rendered
  mockup first, and each visual slice gets its operator-approval criterion at creation. Tests,
  generated JSON, build and lint cannot show two slices overprinting each other.

### Capturing a design interview

A design interview that settles a milestone ends in one capture task, created inside the
milestone right after the spec and milestone. The spec holds the confirmed decisions and the
slicing; each decision names its payoff measure and bar, and the slice or check task that
carries the measure. The capture task ships the decision record in its own PR, before any cohort
task starts:

```bash
starpulse task create "Record the <decision> policy" --milestone m-<N> --documentation doc-<N> ...
starpulse milestone edit m-<N> --adr <path>
starpulse task create "<slice>" --milestone m-<N> --dependency PROJ-<capture> --status waiting ...
```

It closes at `Review` like any PR task. Cohort tasks that enforce the decision name it with
`--dependency`, unless an earlier slice they already depend on does. Create each one `Waiting`
while any dependency is unfinished. Re-run `milestone edit --adr` if the record's path is
renamed.

## Duplicate checks at creation

Before `task create`, run `starpulse search "<terms>"`. Each query expresses behavior or an
acceptance criterion from the requested work; paths and titles are search terms, never proof two
tasks share scope. Search matches every word as literal text, in title, description, criteria and
notes. A non-terminal hit with the same requested outcome is the duplicate: resume it or depend
on it, never create a replacement. Record the queries in the new task's Description.

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
attention` and the fix's `Done` releases it. A check task is the exception: one that measured a
miss parks `--operator` for the operator's close (Validation, below), and the fix carries the
outcome.

A task whose pull request already merged is never parked, for any reason: it closes with
`starpulse task review`, which needs no deliver run then. A wait you can verify now, such as a
pull request's merge state, is verified, not parked. A task that never started and needs the
operator present, such as an interview, stays `Ready`; the session that claims it asks, and
parks `--operator` when the operator is not there to answer.

A `Waiting` task has either a dependency or Start Criteria, never both and never neither.
Creating a task with an unresolved dependency lands it `Waiting`, and starting it is refused
until every dependency is `Done`.

## Evidence only the merge produces

A delivery task's Acceptance Criteria are what its pull request shows before the merge.
Evidence only the merge can produce (a live row, a metric, a scheduled run, a latency on the
deployed page) is a check task, created `Waiting` on Start Criteria that observe the merged
change (Validation, below); a mechanism claim is proved before `Review` instead (Prove now,
below). A check that needs operator approval to run, such as a load burst against a live
service, or a person's judgement, such as a render on a device, is proved before `Review` or
run with the operator.

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

**After two consecutive first-verdict misses on the same duration or latency Outcome target where
a diagnosis has already named a path floor, the next slice is `kind-decide` (architecture change
or Outcome revise), never another fix/check pair that re-measures the same target.** A single
unreachable threshold parks its check `--operator`.

Never gate on an incidental event, such as an unrelated commit touching a path, when a deliberate
trigger exists: a live retention prune that a seeded test or one manual timer run shows the day
it merges needs no 23-day wait.

A criterion's `kind` is one of the closed set the board's configuration supports (typically a
SQL or metric query compared against `at_least`, `at_most` or `equals`, a log-metric query, a
workflow-run status, and git kinds for a path changed or unchanged since a date, or a submodule
pin reaching a commit). A date-only `since` counts from 00:00 UTC; an ISO-8601 timestamp counts
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

When no kind observes the awaited condition, make it observable; never park it with `--operator`.
Create a delivery task that publishes the condition as a metric or a table row, and park the
waiting task now with `--until` on the criterion that reads it: a metric series that does not
exist yet does not pass, so the criterion can name it before the delivery merges. Example: a
check waiting for 50 rows in a local JSONL ledger gets a task exporting the row count as a gauge,
and parks with `--until '{id: rows-50, kind: prom, expr: <gauge>, at_least: 50}'`.

**Start Criteria gate only autopilot's claim.** An explicit operator start claims the task
(`starpulse task claim`) whatever its criteria say. Whoever works it checks the real condition
live and closes the task when it holds. No automated evaluator closes one.

**A check task closes on its first verdict.** A check task is one typed `check`, titled
Validate, Verify or Check, or labelled `validation`. When it measures its criterion, it closes
`Done` with that verdict, pass or miss, recorded with `starpulse task verdict TASK CHECK pass`
or `miss --evidence ... --fix PROJ-M`:

- A pass checks each criterion and closes through the project's `finalize` step.
- A miss records what it measured and forks the fix as its own task. The miss quotes the failing
  unit's or step's own error line, from its journal or job log, and names a cause only from that
  line, never from a fault seen nearby. `Done` needs every criterion checked, so the check then
  parks `--operator` naming the miss and its fix, for the operator to close.
- A fix task that declines its change re-scopes or archives its paired fresh check in the same
  step; left queued, that check misses by construction.
- A check re-parks only when it could not measure, such as a window with no sample yet, and then
  on a gate that counts the sample it needs, never on its fix. When the criterion passed without
  the condition holding, tighten it before re-parking.
- A check whose threshold a prior diagnosis showed unreachable on its path parks with
  `--operator` naming the threshold decision instead of re-measuring it.
