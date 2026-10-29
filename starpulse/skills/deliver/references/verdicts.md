# Delivery Verdicts Other Than Green

Read when `starpulse command run deliver` prints blocked or crashed, or when a criterion only the merge or its
deploy can prove.

## Blocked

The checks cannot finish without a person or another board task. When the blocker is a board task, park this task on it with `starpulse task park <task> --until-task <blocker>` and end the turn, or `--until-task <blocker>#<K>` when only that task's open criterion K is needed (the park releases once K is checked, though the blocker stays open) or `--until '<criterion naming the fact>'` when the need is a fact a check can observe; a background watcher is for waits that are not tasks. Otherwise park it on the person with `starpulse task park <task> --operator '<what blocks, ending with the question>'`, ask that question in the reply, and end the turn; a task waiting on a person is never left In Progress.
## Crashed

The delivery failed in its own machinery, not on the change, such as a traceback or a misconfigured step. Search the board for the task that owns the fault (`starpulse search <two or three terms from the error>`), file one when none exists, park this task on the fact the fault withholds with `--until '<criterion naming the fact>'`, or on the owner's criterion for it with `starpulse task park <task> --until-task <owner>#<K>`, and end the turn; park on the whole owner (`--until-task <owner>`) only when the fix is the whole need, because a dependency on a task that stays open for other criteria never releases. Never fix the delivery pipeline from this task or on the default branch, never finish its remaining steps by hand, and never ask a person to choose either; when the owner merges, deliver again and it reuses the open PR.
## Merge-only evidence

A criterion only the merge or its deploy can prove never blocks the delivery and never earns a question to a person. It is a checkup task, however soon its evidence lands: file it, `starpulse task create '<check>' --type check`, and park that task on the merged change with `starpulse task park <check> --until '{id: merged, kind: <git path-changed kind>, path: <changed path>, since: <ISO-8601 now>}'`, using the kind name the project's board lists for a path changed since an instant. Check this task's other criteria, take the green delivery through step 5 to review, and end the turn.
