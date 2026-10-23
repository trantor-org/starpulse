---
name: tdd
description: Drives a claimed StarPulse task's behavior change through recorded red, green and refactor cycles, then checkpoints each passed criterion and reconciles the docs. Use after a task's worktree exists and before its delivery, when changing code that alters observable behavior, fixing a defect, or resuming a build after a reset. Not for a change with no behavior, such as a doc-only edit, which goes straight to the criteria and docs steps.
machine: machine.yaml
---

# Test-Driven Build

This phase runs in the task's worktree and ends when every criterion this phase can prove is checkpointed and the
docs match the change. Drive one observable behavior at a time.

A step named `starpulse command run NAME` is the project's own command. When it exits 4 the project maps no
`NAME`: do that step as the project's `AGENTS.md` says.

## 1. Prove red

1. Write the smallest test that states one behavior the task asks for, at the lowest tier that observes it.
2. Run it: `starpulse command run test --task PROJ-45 -- <test paths>`. The project's runner records the verdict on
   the task.
3. Continue only when the assertion fails because the behavior is absent or the defect is present. Setup, import
   or environment errors are not red: fix the test and run it again.

Done when the run records red for the intended reason.

## 2. Make it green

Change only enough production code to satisfy that test. Run the same command. When it still fails, change the
code, never the assertion, unless the test itself was wrong.

Done when the same command records green.

## 3. Refactor while green

Remove duplication and name things for the domain. Rerun the focused test after each meaningful refactor. Keep one
behavior per cycle: the next behavior starts again at step 1.

Done when the code reads as the project's code does and the focused test is still green.

## 4. Checkpoint the criteria

Checkpoint every passed criterion that has no entry yet: `starpulse task checkpoint-ac PROJ-45 <criterion>
<evidence>`, with the command and its result as evidence. A criterion with no behavior, such as a file that must
exist, is checkpointed the same way once its command passes. Run the project's checks on the changed files with
`starpulse command run check -- <changed paths>` and fix what they report.

Done when every criterion this phase can prove has an entry and the checks pass.

## 5. Reconcile the docs

Update each doc the change makes wrong, in place, and add one only where a reader would otherwise miss the change.
Run the project's doc checks on what you edited. Record the docs touched, or that none needed a change, in a task
comment.

Done when the docs match the change and a task comment says which ones changed.

## Keep the build bounded

- Focused test runs never replace the affected suite, the checks or the docs step.
- After a reset, start from `starpulse task show PROJ-45` and the working doc's Next step: the recorded red and
  green verdicts say where the cycle stands.
