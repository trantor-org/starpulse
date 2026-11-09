# Specs and Slicing

Read when writing a milestone spec, slicing one into tasks, or capturing a design interview.
Creating the milestone itself and its retro is task-conventions.md, Milestones; check tasks
and Start Criteria are task-conventions.md, Validation.

## Writing the spec

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

## Slicing a spec

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
  service answering after the merge applies (task-conventions.md, Validation). The slice's Acceptance
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

## Capturing a design interview

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
