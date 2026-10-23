---
name: starting-task
description: Turns a request into a claimed StarPulse task with command-backed gates and a ready worktree, before any implementation edit. Use when starting non-trivial work on a project whose board runs on StarPulse, when told to start or pick up a task (PROJ-45, TASK-12), or when resuming a task after a reset. Not for a one-line change the project lets ship without a task.
machine: machine.yaml
---

# Starting a Task

This phase ends when the task is claimed, its gates are recorded and its worktree exists. Size the task from what
the work spans (files, modules, tests, docs), never from words such as quick or small.

A step named `starpulse command run NAME` is the project's own command. When it exits 4 the project maps no
`NAME`: do that step as the project's `AGENTS.md` says.

## 1. Find the task or file it

1. When the request names a task, run `starpulse task show PROJ-45` and read its description, criteria, comments
   and linked docs, then go to step 2.
2. Otherwise search before filing: `starpulse search <two or three distinctive terms>`. An unfinished hit that asks
   for the same outcome is the task: resume it and comment the new evidence. Never file a replacement because it is
   paused or an earlier attempt failed.
3. With no such hit, file one with `starpulse task create`: a title naming the outcome, the request in its
   description, and Acceptance Criteria that are independent completion gates, each checked by a command. A
   criterion that only a merged change can prove belongs to a separate check task that waits on the merge.
4. When two or more tasks come from one plan, give them a milestone (`starpulse milestone add`) and a spec
   (`starpulse doc create`) before the tasks.

Done when you can name one task whose criteria each name the command that proves it.

## 2. Claim it

Claim the task before checking it against code: `starpulse task claim PROJ-45`. The claim moves it to In Progress
under your session, so no other session picks it up. A refusal names the session that holds it, or the task you
already hold: finish or park that one first, and never route around the refusal.

Done when `starpulse task show PROJ-45` lists your session as the holder.

## 3. Record the route

1. Set an ordered plan and the task's Definition of Done with `starpulse task edit PROJ-45 --plan ... --dod ...`.
2. Record durable decisions and rejected options with `--append-notes`, and decide whether the work needs an
   architecture decision record.
3. Keep a working doc that says where the work stands, so a fresh session resumes from it: file it with
   `starpulse doc create` titled `PROJ-45 working notes` and link it with `starpulse task edit PROJ-45
   --documentation`. Give it four headings: Current state, Decisions, Open questions, Next step. Next step names
   the command a fresh session runs first. Update it at each decision, criterion and dead end.

Done when the task has a plan, a Definition of Done and a linked working doc.

## 4. Make the worktree

Run `starpulse command run start --task PROJ-45`. It prints the task's worktree; a rerun reuses it rather than
making a second. Give every later edit and command that worktree's absolute path, and never work on the default
branch.

Done when `git -C <worktree> rev-parse --show-toplevel` prints the worktree.

## Keep the scope bounded

- When the work cannot continue, park it with the one reason that holds: `starpulse task park PROJ-45` with
  `--until-task PROJ-46`, `--until '<criterion>'` for a condition a check can observe, or
  `--operator '<what they decide>'` when only a person can continue. Verify a wait you can check now instead of
  parking on it.
- When discovery turns up material work beyond the criteria, comment one recommendation to fork it as a separate
  task. Do not grow the current task, and do not stop it unless the new work blocks a criterion.
- After a reset, start from `starpulse task show PROJ-45` and the working doc's Next step, never from memory.
