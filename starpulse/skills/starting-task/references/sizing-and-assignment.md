# Sizing and Assignment

How to give a task its kind and size, for one task or for every slice of a plan. The kind
vocabulary and the size rubric are here; which agent profile a kind and size map to is the
project's own table, set in its board configuration and read with `starpulse task show`.

## Kinds

Every task but an `unattended` one carries exactly one kind label:

| Label | The task… | Example |
|---|---|---|
| `kind-mechanical` | applies a change fully specified in its brief | rename, version bump, lint or link fix |
| `kind-execute` | implements a settled plan, making local implementation choices | an `execution-ready` slice |
| `kind-diagnose` | finds the unknown cause of something broken | a bug with no reproduced root cause, an incident |
| `kind-spike` | measures, evaluates or researches, and reports | an evaluation, a benchmark |
| `kind-decide` | produces a design, a decision or a plan other work depends on | an ADR, a decision spike, slicing a milestone, a governance change |

## Sizes

Sizes are `size-1`, `size-2`, `size-3`, `size-5`, `size-8` (Fibonacci points). Start from the
scope, then step up one value per aggravating driver: the cause or approach is unknown; it
touches live state, a migration or a shared interface; it spans two repositories merged in
order (package, then the pin that consumes it); or its criteria depend on an external system.
An `Operator approved the render` criterion is two drivers.

| Size | Base scope |
|---|---|
| 1 | one file, a few lines |
| 2 | up to 3 files, one subsystem |
| 3 | up to 10 files, one subsystem |
| 5 | up to 15 files or two subsystems |
| 8 | more than 15 files or cross-cutting |

A deletion-only change is sized by subsystems, not files. A docstring-only rewrite in one
repository is size 3.

## Size one task

1. Pick the kind from what the task is trying to accomplish. A change to project policy (the
   agent instructions, a skill, a decision record, a lint rule, a board convention) is
   `kind-decide` whatever its size. The exception is an edit that changes no rule or behavior
   (rewording, a typo, a link fix): give it `kind-execute` and a `wording-only` label. Among
   the three open-ended kinds, ask what the report is for: a task that measures, evaluates or
   researches and reports, deciding nothing (a benchmark, a comparison), is `kind-spike`; one
   whose output is a design, a decision record or a plan other work depends on is
   `kind-decide`; one chasing something broken or being troubleshot is `kind-diagnose`. A
   spike whose report leads to a decision files that decision as its own `kind-decide` task.
2. List the files and subsystems the change touches, take the base size for that scope, then
   step up one value per aggravating driver that applies. Name each driver you counted.
   - Starting a scratch engine or running an eval against a live model server counts as the
     live-state driver. A documented, idempotent apply path (a checked-in dashboard push, a
     container recreate, an apply-on-merge job running a migration) does not; a hand-run or
     first-of-its-kind live change does.
   - An `Operator approved the render` criterion steps up two values, not one: render rounds
     and operator wait, not code, set its length, and most tasks stepped once ran over. A
     check that drives a burst against a live service or exposes one on the network takes
     both the live-state and external-system drivers, since the operator must approve the run.
   - A slice with both the render criterion and the two-repository driver starts at 8.
   - A slice that edits only a submodule whose pin a bot moves does not take the
     two-repository driver.
   - Size a sweep from a count of the sites it will touch (a `rg` count), not from its brief.
     The file count includes tests, docs and package registration. A slice that adds a new
     package or a new live consumer starts at 8: execute slices sized 3-5 for such work landed
     20-33 files.
   - A migration that rewrites existing tests counts each rewritten test file and takes the
     migration driver. A planned pure move (no behavior change, destinations and import
     rewrites already listed) in one repository is size 3 whatever its file count, or 5 when
     it rewires an import contract or a CI test selector; the two-repository driver still
     applies on top.
   - A wide rename (over 30 files) cut alongside a concurrent cohort steps up one for rebase
     contention. A move within one module whose tests share one context steps down one.
   - A fix that adds a migration or touches two production files takes the fix-scope step;
     count test files and every patched module.
   - A `kind-decide` task that runs a full mockup interview with the operator is size 8
     whatever its scope and is never split for reaching 13: review rounds run at the
     operator's pace.
   - A `kind-diagnose` task whose gate is a multi-hour end-to-end run that stops at the first
     failure steps up one size, and each further fault the run uncovers is forked unless it
     blocks the gate.
   - A cutover slice that rewires a live caller and retires the old path starts at 8.
   - Forecast compaction last: a task whose scope, once the drivers are counted, runs past
     about 70 agent steps or reads large outputs (logs, a corpus scan, a full test run) is
     forecast to compact. Step it up one size; at slicing, split it instead when a seam keeps
     each part under about 70 steps. A planned mechanical migration is the exception: a
     context forecast alone never sizes it at 8, so size it by its other drivers.
3. State kind, size, profile and a one-line reason in your reply before the `create`. Look
   the profile up in the project's table; an assignee that departs from it needs a comment
   recording the evidence and the reason. A fast-tier profile goes only to unattended
   `kind-execute` or `kind-mechanical` work: an `attended` mode, a type that waits on the
   operator or judges live evidence, or an operator criterion lifts it to the standard tier at
   the same effort. A check or validate task's verdict is a judgement over live evidence,
   never a fast-tier call: where the table lifts that type off its fastest tier, the lifted
   profile is the default.
4. Create or update the task with its labels:

   ```bash
   starpulse task create "<title>" --label kind-execute --label size-3 --priority medium --type story ...
   starpulse task edit PROJ-91 --label kind-diagnose --label size-5
   ```

Size work the operator will run by hand too: its profile is the model and effort to start the
operator's session with; never assign it to a person. Only an `unattended` task is exempt from
sizing.

## Size a plan's slices

Do the steps above for every slice before proposing the cohort, then:

1. Add `Kind`, `Size` and `Profile` columns to the milestone spec's slicing table, with the
   one-line reason beside each row, so the cohort proposal shows which agent runs each slice.
2. A slice that sizes to 13 is split before any task exists. State its size and the drivers
   that reached 13, then cut it along a seam that leaves each part independently verifiable,
   re-size the parts, and repeat until none reaches 13. A size 13 is refused. A
   slice expected past the size-8 p90 is split before filing the same way, even at
   size 8 or below. A mockup-interview task stays one size-8 slice. A slice forecast to compact is split the same
   way when a seam exists, else stepped up, except a planned mechanical migration.
   Size a mutation-kill slice by the source and test files it touches, not its survivor count,
   and cap it at about one module or ~15 functions.
3. Slicing the milestone is itself `kind-decide` work.
4. Run the project's `check` command (`starpulse command run check`) on the current default
   branch and file a blocker slice before a parallel wave.
5. Re-diff each file a slice hunts against the default branch before `create`.
6. Create each task with its kind and size in the approved dependency order; assign a profile
   only where the slice departs from the table.

The slicing table's profile is the one a task defaults to. If they differ, the table is wrong.
