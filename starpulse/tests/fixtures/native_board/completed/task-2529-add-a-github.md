---
id: TASK-2529
title: 'Add a GitHub adapter for pull requests, checks and Copilot'
status: Done
assignee:
  - '@agent-standard-high'
created_date: '2026-10-03 17:10'
updated_date: '2026-10-06 23:32'
labels:
  - agent-resolvable
  - kind-execute
  - size-8
milestone: m-80
dependencies:
  - TASK-2433
  - TASK-2432
  - TASK-2520
references:
  - 'https://github.com/trantor-org/starpulse/pull/70'
documentation:
  - >-
    backlog/docs/specs/doc-82 -
    Flow-View-hub-configured-flow-graph-and-orbit-card.md
modified_files:
  - 'trantor-org/starpulse:README.md'
  - 'trantor-org/starpulse:starpulse/github.py'
  - 'trantor-org/starpulse:starpulse/github_actions.py'
  - 'trantor-org/starpulse:starpulse/machines/copilot.yaml'
  - 'trantor-org/starpulse:starpulse/machines/github-pull-request.yaml'
  - 'trantor-org/starpulse:starpulse/tests/fixtures/github/copilot-pull.json'
  - 'trantor-org/starpulse:starpulse/tests/fixtures/github/reviewed-pull.json'
  - 'trantor-org/starpulse:starpulse/tests/unit/test_github.py'
priority: medium
type: feature
ordinal: 2577000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Decision H13 of doc-82 and the ADR's Copilot mapping. Actions runs belong to m-78 (TASK-2511).

ADR: The Flow View Hub Draws a Configured Flow Graph Above the Board. Spec: doc-82.

## Duplicate Search

github adapter pull requests copilot

## Duplicate Resolution

Distinct scope: the only candidate is TASK-2433, the slicing task that created this slice. Also distinct: TASK-2511, TASK-2516 are the m-80 retro, sibling hub slices, or shipped trantor-only flow-view work (TASK-2356 is trantor's /api/history over its own Postgres machine events), none covering this slice's package scope.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The adapter passes the shared kit on recorded fixtures
- [x] #2 Fixtures pin copilot_work_started/finished timeline events, `dynamic` Copilot runs and copilot-pull-request-reviewer[bot] reviews and map them to machine events keyed PR, branch, task
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 Task-specific completion outcomes are met.
- [x] #2 Relevant verification, documentation, and pull-request gates have passed.
- [x] #3 Implementation Notes, Modified Files, and the final summary reflect the delivered state.
- [x] #4 The completing-tasks skill was invoked before task closure.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Child clone trantor-org/starpulse in .tmp/, branch claude/task-2529-github-adapter from origin/main.
2. RED/GREEN AC2: record fixtures off public Copilot PRs (timeline with copilot_work_started/finished, dynamic runs, reviewer-bot review, PR, check runs); pure mapper github.py turns a PR bundle into MachineEvents on a shipped copilot machine and pull-request machine, keyed task (branch via TaskKeys) else run owner/repo#N; tests pin the event names so a rename fails.
3. RED/GREEN AC1: GitHubAdapterKit subclass (MachineEventsAdapterKit) over the fixtures; REST reader on github_actions Transport; follow loop publishing with deterministic event_id so a re-read never duplicates.
4. Update README and writing-starpulse-adapters skill; gates: package pytest, ruff, ty per package CI; child PR in starpulse; trantor gitlink bump is Renovate's.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Package work ships as a PR in trantor-org/starpulse (child); trantor gitlink bump is Renovate's, never committed here. ADR decision: none needed; H13 of doc-82 and the Flow View hub ADR (Copilot mapping) cover it. Fixtures are recorded off public Copilot PRs (jeremytrimble/specview#46 and #38), scrubbed of ids and text.

**Holder:** 37a688b6-bfa8-4d9c-8b81-0b83aba08da1
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
created: 2026-10-06 22:50
---
[board-autopilot] (board-dependency-reconciliation) moved this task to `Ready` because every native dependency is `Done`. Its autonomy label is unchanged.
---

created: 2026-10-06 22:52
---
**Session Link:** https://claude.ai/code/session_015F8CSJQVtTogMVMPgHN2QC — local Claude session `37a688b6-bfa8-4d9c-8b81-0b83aba08da1`, reopen with `claude --resume 37a688b6-bfa8-4d9c-8b81-0b83aba08da1`
---

created: 2026-10-06 23:11
---
Verified AC #1: `cd /home/adinb/trantor/.claude/worktrees/task-2529-add-a-github/.tmp/starpulse && uv run --no-sync pytest starpulse/tests/unit/test_github.py -q -p no:cacheprovider -k TestGitHubAdapter` exited 0

```
......                                                                   [100%]
6 passed, 15 deselected in 0.54s
```
---

created: 2026-10-06 23:11
---
Verified AC #2: `cd /home/adinb/trantor/.claude/worktrees/task-2529-add-a-github/.tmp/starpulse && uv run --no-sync pytest starpulse/tests/unit/test_github.py -q -p no:cacheprovider -k "copilot or reviewer or merged or keyed"` exited 0

```
.......                                                                  [100%]
7 passed, 14 deselected in 0.08s
```
---

created: 2026-10-06 23:29
---
Child PR trantor-org/starpulse#70: python, ic, web, build green on 9955334, no conflicts, 0 open review threads. Parent gitlink bump left to Renovate. Not recorded: a real 'Running Copilot Code Review' run; the test renames a recorded agent run to exercise the ADR's name. Follow-up worth filing after the pin bump: describe the adapter in docs/services/ai/starpulse.md.
---

created: 2026-10-06 23:32
---
Closed on merge evidence: trantor-org/starpulse#70 merged as 9893f059f2941cba8c8f288f851bf592d3ae3475 (PR #70)
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
A GitHub adapter now turns pull requests, their checks and Copilot work (timeline events, dynamic runs, bot reviews) into keyed machine events, with two shipped machines and recorded fixtures.
<!-- SECTION:FINAL_SUMMARY:END -->
