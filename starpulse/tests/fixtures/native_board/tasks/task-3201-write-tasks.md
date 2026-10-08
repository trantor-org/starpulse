---
id: TASK-3201
title: >-
  Write tasks through StarPulse's native board instead of the backlog binary in
  the board CLI
status: Waiting
assignee:
  - '@agent-standard-high'
created_date: '2026-10-07 21:53'
labels:
  - agent-resolvable
  - kind-execute
  - size-8
milestone: m-115
dependencies:
  - TASK-3200
documentation:
  - >-
    backlog/docs/specs/doc-116 -
    Trantors-board-moves-from-backlog-to-StarPulses-native-board.md
priority: high
type: task
ordinal: 3240000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Spec doc-116 D3. Replace the 13 task call sites in `lib/backlog_workflow/tasks.py` that run `paths.BACKLOG_BIN` (task edit/create/list/view/complete/archive and comments) with StarPulse's declared native-board writers and reader, against the existing `backlog/` root (same file format, so no storage move yet). Output shapes `bin/backlog_task.py` prints stay the same. Starts once the starpulse gitlink contains P3. Cites ADRs: Trantor Keeps Its Board on StarPulse's Native Markdown Board; Trantor Consumes StarPulse Through the Contract an Installed User Has; Board Writers Enforce Declared Machine Guards.

## Duplicate Search

board cli task writes without backlog binary; replace BACKLOG_BIN task edit native writer

## Duplicate Resolution

No candidate moves the board CLI's writes off the backlog binary. TASK-1124 (Done) created the fork this cohort retires; TASK-2704, TASK-2705, TASK-2999 (Done) built the native board writers this slice calls; TASK-23 (Done) routed Backlog.md through the gateway; TASK-1825, TASK-1875 (Done) are lane and gate rules; TASK-145, TASK-59, TASK-69, TASK-70, TASK-96 (Done) and TASK-253 (Archived) match on words only. Distinct scope.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 No task call site runs the backlog binary: `! grep -nE 'BACKLOG_BIN\), "task"' lib/backlog_workflow/tasks.py`
- [ ] #2 `uv run pytest lib/backlog_workflow` passes
- [ ] #3 Trantor's starpulse import check passes: `make lint`
- [ ] #4 A create, edit, complete and archive on a skill-eval mock board round-trip through `bin/backlog_task.py`: `uv run pytest lib/backlog_workflow -k native_writes`
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Task-specific completion outcomes are met.
- [ ] #2 Relevant verification, documentation, and pull-request gates have passed.
- [ ] #3 Implementation Notes, Modified Files, and the final summary reflect the delivered state.
- [ ] #4 The completing-tasks skill was invoked before task closure.
<!-- DOD:END -->
