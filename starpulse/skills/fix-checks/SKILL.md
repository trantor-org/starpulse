---
name: fix-checks
description: Takes a StarPulse task's pull request with failing checks, including one a merge queue evicted for failed checks, from the failing check names and run link through the logs to a pushed fix and green checks, or parks the task when the fault is not its branch's. Use when a task PR's required check is red, when a merge queue drops a task PR for failing checks, or when review-fix or deliver hands off a red check. Not for review threads or merge conflicts, which review-fix answers, and not for a failing test before delivery.
machine: machine.yaml
---

# Fixing Failing Checks

This phase starts on a task pull request with red checks and ends when its checks are green and the task is back in
review, or when the task is parked on the fault's owner.

A step named `starpulse command run NAME` is the project's own command. When it exits 4 the project maps no
`NAME`: do that step as the project's `AGENTS.md` says.

## 1. Gather the inputs

Hold the task ID, PR number, branch, base branch, the failing check names and the run or queue-run link. Whatever
the hand-off left out, read with `starpulse command run pr-status --arg pr=<number>`.

Done when you can name each failing check and the run that failed it.

## 2. Read each failing check's log

Run `starpulse command run check-logs --arg pr=<number> -- <check name or run link>` for each failing check and
take the first error line, not the last. Read only the slice that names the failing step.

Done when each failing check has the error line that failed it.

## 3. Place the fault

Decide whose fault each failure is, from evidence, never from the branch's diff alone:

- Branch fault: the error names code, tests or config the branch changed, or it fails only on this branch.
- Base fault: the same check fails on the base branch's latest run, or on other branches with the same error.
- Flaky: the failure does not touch the branch's change and the same check passed on an identical rerun or on the
  base branch.

Done when each failure carries one of those three labels and the run that shows it.

## 4. Fix a branch fault

1. A failure that changes behavior gets a failing test first, then the fix; rerun with
   `starpulse command run test --task PROJ-45 -- <test paths>`.
2. Run `starpulse command run check -- <changed paths>`; once it passes, the change goes back to delivery, which
   pushes it and waits for green checks again. Return to step 1 after it.

Done when the PR's head holds every fix and its checks are green.

## 5. Park a fault that is not the branch's

A base fault or a flaky check has one owner task: find it with `starpulse search <check name> <error terms>` or file
it, comment the run link, then park with `starpulse task park PROJ-45 --until-task PROJ-46`. A flaky check the
branch did not touch may go back through delivery once first; a second failure of it parks.

Done when the task waits on the owner, or a redelivery turned the check green.

## 6. Move the task to review

When every check is green, run `starpulse task review PROJ-45 --ref <PR URL> --summary '<outcome>'`. A refusal names
the rule that failed and the step that satisfies it: do that step, then run the move again.

Done when `starpulse task show PROJ-45` shows the task in review with the PR linked.

## Keep the loop bounded

- Fix only the failing checks; a finding beyond the task's criteria becomes a recommendation to fork it.
- Never skip, disable or bypass a required check to turn it green.
- After a reset, start from `starpulse task show PROJ-45` and a fresh pr-status read.
