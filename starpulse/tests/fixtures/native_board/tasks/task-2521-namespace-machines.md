---
id: TASK-2521
title: >-
  Namespace machines by repository and merge them only when compiled definitions
  hash equal
status: Done
assignee:
  - '@agent-standard-high'
created_date: '2026-10-03 17:08'
updated_date: '2026-10-06 22:28'
labels:
  - agent-resolvable
  - kind-execute
  - size-5
milestone: m-80
dependencies:
  - TASK-2433
  - TASK-2432
  - TASK-2517
references:
  - 'https://github.com/trantor-org/starpulse/pull/64'
documentation:
  - >-
    backlog/docs/specs/doc-82 -
    Flow-View-hub-configured-flow-graph-and-orbit-card.md
modified_files:
  - starpulse/machine_namespace.py
  - starpulse/tests/unit/test_machine_namespace.py
priority: medium
type: feature
ordinal: 2569000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Decision H6 of doc-82. Machines are `<repo>/<machine>`; two merge only when the compiled definition hashes equal; a differing one carries drift and stays out of the merged graph.

ADR: The Flow View Hub Draws a Configured Flow Graph Above the Board. Spec: doc-82.

## Duplicate Search

flow view machine namespace hash drift

## Duplicate Resolution

Distinct scope: the only candidate is TASK-2433, the slicing task that created this slice. Also distinct: TASK-2420, TASK-2430 are the m-80 retro, sibling hub slices, or shipped trantor-only flow-view work (TASK-2356 is trantor's /api/history over its own Postgres machine events), none covering this slice's package scope.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Two repositories with equal YAML merge; a one-transition change splits them and records drift with both hashes and the transition diff
- [x] #2 Reordering YAML keys or states without semantic change keeps the hash equal (the hash is over the compiled definition)
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
1. Clone trantor-org/starpulse into the worktree's .tmp/ on claude/task-2521-namespace-machines; uv sync.
2. RED/GREEN: starpulse/machine_namespace.py (hub-side, pure, not public surface). A compiled definition reduces to a sorted set of facts (states, flattened transitions with guards and actions, bindings, writers, one-level flows inlined); its sha256 is the hash, so key, state, event and from-list order never change it, and the facts' set difference is the diff.
3. Machines are namespaced <repo>/<machine>; merge() groups sources by machine name, merges those whose hash equals the baseline (most repos, ties to the smallest hash), and returns a Drift record (namespaced id, both hashes, added/removed facts) for each other source, kept out of the merged graph.
4. Tests: AC1 equal YAML merge; one-transition change splits and records drift with both hashes and diff. AC2 reordering keys/states/events/from-lists keeps the hash. Plus guard, flow-child, tie-break and duplicate-source cases.
5. README/docs current-state edit if the surface needs it; lint gates; child PR in trantor-org/starpulse; trantor gitlink bump is Renovate's.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Package work ships as a PR in trantor-org/starpulse (child); the trantor gitlink bump is Renovate's, never committed here (completing-tasks, edited submodule). ADR decision: none needed; H6 of doc-82 and the Flow View Hub ADR (Drift is drawn, not merged) cover it. Not persisting drift: the ACs ask for records returned by the merge; the hub slices that register sources own storage.

**Holder:** 8844d581-ad5d-4caa-9ad4-d6b7c9e4fadf
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
created: 2026-10-06 22:08
---
[board-autopilot] (board-dependency-reconciliation) moved this task to `Ready` because every native dependency is `Done`. Its autonomy label is unchanged.
---

created: 2026-10-06 22:11
---
**Session Link:** https://claude.ai/code/session_01XSQ9zohVs3BmsEijv1Nhj2 — local Claude session `8844d581-ad5d-4caa-9ad4-d6b7c9e4fadf`, reopen with `claude --resume 8844d581-ad5d-4caa-9ad4-d6b7c9e4fadf`
---

created: 2026-10-06 22:18
---
Verified AC #1: `uv run --project /home/adinb/trantor/.claude/worktrees/task-2521-namespace-machines/.tmp/starpulse --all-extras pytest /home/adinb/trantor/.claude/worktrees/task-2521-namespace-machines/.tmp/starpulse/starpulse/tests/unit/test_machine_namespace.py -q -k 'TestMergingAcrossRepositories'` exited 0

```
.....                                                                    [100%]
5 passed, 6 deselected in 31.42s
```
---

created: 2026-10-06 22:18
---
Verified AC #2: `uv run --project /home/adinb/trantor/.claude/worktrees/task-2521-namespace-machines/.tmp/starpulse --all-extras pytest /home/adinb/trantor/.claude/worktrees/task-2521-namespace-machines/.tmp/starpulse/starpulse/tests/unit/test_machine_namespace.py -q -k 'TestTheDefinitionHash'` exited 0

```
......                                                                   [100%]
6 passed, 5 deselected in 1.08s
```
---

created: 2026-10-06 22:27
---
Child PR trantor-org/starpulse#64 (no trantor tracked change; gitlink bump is Renovate's). RED/GREEN in test_machine_namespace.py: hash order-invariance and merge/drift. Full starpulse suite 1429 passed; ruff check clean; PR CI python/ic/web/build green, mergeable CLEAN, 0 review threads. No docs or ADR owed: module is internal and unwired. Orphan walk: nothing removed; new module has no consumer yet (later hub slices).
---

created: 2026-10-06 22:28
---
Closed on merge evidence: trantor-org/starpulse#64 merged as 02d715fd22083a588ab4b17411c1cf4832cf970f (PR #64)
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
starpulse.machine_namespace names machines <repo>/<machine>, hashes the compiled definition, and merges sources only on equal hashes, recording drift for the rest.
<!-- SECTION:FINAL_SUMMARY:END -->
