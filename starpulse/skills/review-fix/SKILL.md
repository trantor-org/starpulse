---
name: review-fix
description: Takes a StarPulse task's ready pull request through its review threads, merge conflicts and checks until nothing actionable remains, then moves the task to review. Use when a task's PR is ready, when review comments, a conflict or a red check arrive on an open task PR, or when a move to review is refused. Not for the first delivery of a change, and not for merging, which a person does.
machine: machine.yaml
---

# Fixing Review Findings

This phase starts on a ready pull request and ends when the task is in review with nothing actionable left on its
PR, or when a fix sends the change back through delivery.

A step named `starpulse command run NAME` is the project's own command. When it exits 4 the project maps no
`NAME`: do that step as the project's `AGENTS.md` says.

## 1. Read what the PR needs

Run `starpulse command run pr-status --arg pr=<number>`. It reports merge conflicts, failing checks and unresolved
review threads.

Done when you hold the list of conflicts, red checks and open threads, or know it is empty.

## 2. Answer each finding

1. For each thread, decide whether it is correct. A correct finding that changes behavior gets a failing test
   first, then the fix; rerun with `starpulse command run test --task PROJ-45 -- <test paths>`.
2. A finding you reject gets a reply that names the evidence, never a silent resolve.
3. Resolve a conflict by rebasing onto the default branch, never by merging it in.
4. Checkpoint any criterion the fixes touched with `starpulse task checkpoint-ac`.

Done when every thread has a fix or a reasoned reply.

## 3. Send fixes back through delivery

When the fixes changed a tracked file, run `starpulse command run check -- <changed paths>`; once it passes, the
change goes back to delivery, which pushes it and waits for green checks again. Return to step 1 after it.

Done when the PR's head holds every fix and its checks are green.

## 4. Move the task to review

When nothing actionable remains, run `starpulse task review PROJ-45 --ref <PR URL> --summary '<outcome>'`. A
refusal names the rule that failed and the step that satisfies it: do that step, then run the move again. Never
route around a refusal.

Done when `starpulse task show PROJ-45` shows the task in review with the PR linked.

## Keep the loop bounded

- Fix only what the review asks; a finding beyond the task's criteria becomes a recommendation to fork it.
- After a reset, start from `starpulse task show PROJ-45`, the working doc's Next step, and a fresh pr-status read.
