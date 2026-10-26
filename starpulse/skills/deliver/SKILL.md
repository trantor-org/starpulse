---
name: deliver
description: Carries a built StarPulse task from final gates through commit, push, pull request and green CI to a ready PR, or closes a task that ships no PR. Use when a task's build is done and its change must ship, when asked to commit, push, open or ready a PR, watch its CI, or finish a task, and when asked for a shortcut such as committing straight to the default branch or an admin merge. Not for answering review comments on an open PR.
machine: machine.yaml
---

# Delivering a Task

This phase ends when the task's one pull request is ready with green checks, or, for a task that ships no PR, when
the task is finalized. The project's people merge; an agent never does.

A step named `starpulse command run NAME` is the project's own command. When it exits 4 the project maps no
`NAME`: do that step as the project's `AGENTS.md` says.

## 1. Run the final gates

1. Run the tests now even if an earlier run passed: `starpulse command run test --task PROJ-45 -- <test paths>`.
   When a test fails because an accepted behavior made its expectation stale, update the expectation and rerun.
2. Run the project's checks on every changed file: `starpulse command run check -- <changed paths>`. Fix what they
   report and rerun until they pass.
3. Checkpoint every passed criterion that has no entry yet with `starpulse task checkpoint-ac PROJ-45 2
   '<command>: <result>'`: the criterion's number, then one quoted evidence string, no flags.
4. For each fork recommended in a task comment, file it as a task or decline it in a comment.

Done when the tests and checks pass on the final tree and every criterion has an entry.

## 2. Close a task that ships no PR

When the task changes no tracked file, such as a spike whose answer is a doc or a decision, skip the rest: run
`starpulse command run finalize --task PROJ-45 --arg summary='<outcome>' --arg comment='<evidence>'`.

Done when `starpulse task show PROJ-45` shows the task finalized.

## 3. Stage and describe the change

1. Stage only the task's own paths. Leave every file another session changed as it is. A change that lives only in
   a submodule ships its PR from the submodule's own task worktree, in the submodule's repository; the parent ships
   no PR and leaves the submodule pin as it is. Run steps 3 to 5 in that child worktree.
2. Write the commit message and the PR body to two files outside the tracked tree. The body names the task, what
   changed, and how each criterion was proven.

Done when the staged diff holds only the task's paths and both files exist.

## 4. Deliver

Run one delivery in the foreground: `starpulse command run deliver --task PROJ-45 --arg message=<file> --arg
body=<file>`. It commits, pushes, opens the task's PR or updates the one already open, waits for its checks, and
prints a verdict.

- green: the checks passed; go to step 5.
- red: read the failing check, fix the cause in the worktree, rerun the final gates, and deliver again.
- blocked: the checks cannot finish without a person or another board task. When the blocker is a board task, park this task on it with `starpulse task park <task> --until-task <blocker>` and end the turn; a background watcher is for waits that are not tasks. Otherwise park it on the person with `starpulse task park <task> --operator '<what blocks, ending with the question>'`, ask that question in the reply, and end the turn; a task waiting on a person is never left In Progress.
- merge-only evidence: a criterion only the merge or its deploy can prove never blocks the delivery and never earns a question to a person. File it as a check task, `starpulse task create '<check>'`, and park that task on the merged change with `starpulse task park <check> --until '{id: merged, kind: <git path-changed kind>, path: <changed path>, since: <ISO-8601 now>}'`, using the kind name the project's board lists for a path changed since an instant. Check this task's other criteria, take the green delivery through step 5 to review, and end the turn.

Done when the delivery prints green.

## 5. Mark the PR ready

Read the PR's state with `starpulse command run pr-status --arg pr=<number>`. When it is still a draft, the
delivery marks it ready on its green verdict; when it is not, mark it ready the way the project's `AGENTS.md`
says.

Then move the task to review with `starpulse task move PROJ-45 review`: the move takes the column's lowercase id.
A refusal names the ids the task can move to and, when a guard refused, the skill that satisfies it. A guard that
wants the PR and evidence recorded takes them in one call instead: `starpulse task review PROJ-45 --ref <pr-url>
--summary '<outcome>' --comment '<evidence>'`.

Done when `starpulse command run pr-status --arg pr=<number>` reports the PR ready with green checks and
`starpulse task show PROJ-45` shows the task in review.

## Decline shortcuts

- Never commit to the default branch, skip the task branch, or base the branch on anything but the default branch.
- Never merge the PR or bypass a required check. A request for one is answered with the PR link and the step that
  remains for a person.
- After a reset, start from `starpulse task show PROJ-45` and the working doc's Next step, then rerun the
  delivery: it reuses the open PR.
