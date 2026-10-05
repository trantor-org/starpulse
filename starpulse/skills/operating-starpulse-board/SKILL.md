---
name: operating-starpulse-board
description: Operates a task board that runs on StarPulse through the starpulse CLI, never by editing task files or calling its HTTP API. Use when a project's board runs on StarPulse and the work is picking what to work on next, finding why a task (PROJ-45, TASK-12) cannot move to a column, moving a task to review, done or another column, or checking what a task waits on.
---

# Operating the StarPulse Board

Every `starpulse` verb here reads the running server and writes one JSON document to stdout. An error is
`{"error", "code"}`. Exit codes: 0 ok, 1 refused or invalid, 2 usage, 3 server or board writer unavailable, 4 not
found. Never edit a task file to change its column: the board's guard decides which moves are legal, and a
hand edit skips it.

## Pick what to work on

1. Run `starpulse board`. Each column is `{state, name, tasks}`; narrow it with `--state`, `--assignee`, `--label` or
   `--milestone`. Take the state ids from this output rather than assuming them.
2. Choose a task in the column that holds ready work whose `waiting_on` is empty. A non-empty `waiting_on` lists the
   dependencies that have not completed.
3. Run `starpulse task show PROJ-45` for its description, pull requests and moves before starting.

Done when you can name the task and why nothing it depends on is open.

## Explain why a task cannot move

1. Run `starpulse task moves PROJ-45`. Each column the task may move to is `{allowed, reason, skill}` as the agent
   meets it.
2. For a column with `allowed: false`, report its `reason`. When `skill` is set, follow that skill: it names the step
   the guard wants done first.
3. A reason that names the operator means only the operator may make that move. Say so and stop; do not route around
   the guard.
4. Run `starpulse task show PROJ-45` and read `waiting_on` when the reason is a dependency.

Done when you can state, for the column asked about, the reason and the one thing that clears it.

## Move a task

1. Run `starpulse task moves PROJ-45` and confirm the target column is `allowed`.
2. Run `starpulse task move PROJ-45 review`, with the column's state id as `task moves` lists it.
3. Read the result: `ok: true` is the move made. `ok: false` with exit 1 is the guard's refusal with its `reason`
   and `skill`; do the skill's step, then move again, and do not retry unchanged. Exit 3 means the board has no
   writer or no server answers; exit 4 means the task is not on the board.

Done when `ok` is true, or you have reported the refusal's reason and skill.

When no server answers, use the `setting-up-starpulse` skill and run `starpulse doctor`.
