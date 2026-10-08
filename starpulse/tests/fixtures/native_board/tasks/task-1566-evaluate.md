---
id: TASK-1566
title: Evaluate and promote a blue Frigate model trained on the new event labels
status: Waiting
assignee:
  - '@agent-standard-high'
created_date: '2026-09-27 17:16'
updated_date: '2026-10-03 17:40'
labels:
  - frigate
  - local-model
  - unraid
  - needs-human
  - kind-execute
  - size-5
dependencies: []
priority: low
type: enhancement
ordinal: 1627000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Split from TASK-2 on 2026-09-27 by operator decision: promotion waits for new labels. Deployed Frigate model is blue_package_plus_local_20260706_1305; latest blue is blue_auto_20260717-232300 (221 paired images). Since then no new label reached training. Once at least 20 new labels are decisioned and auto_blue_retrain_if_ready.py produces a new blue, compare it against the deployed model on held-out frames and promote it if it wins. Promotion follows the manual steps in frigate-custom-model/docs/frigate-custom-model.md and needs operator approval to change Frigate config.

## Start Criteria

The awaited condition is 20 labelled frigate_event_* images in the labeler. TASK-1850 publishes that count as `frigate_labeler_labelled_event_images`; until it ships the series does not exist, the criterion cannot be evaluated and counts as not passing. On 2026-09-28 the labeler held 1 labelled frigate_review_* image and 20 unlabelled frigate_event_* imports.

```yaml
start_criteria:
  - id: labelled-event-images
    kind: prom
    expr: frigate_labeler_labelled_event_images
    prometheus: unraid
    at_least: 20
```
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 latest-blue-manifest.json names a blue trained after TASK-1565 closed, on a dataset including frigate_event_* images
- [ ] #2 An evaluation of that blue against the deployed model on held-out FrontDoor and Backyard frames is recorded on this task
- [ ] #3 The operator's promote-or-keep decision is recorded, and if promoted, `ssh unraid grep model /mnt/user/appdata/frigate/config.yml` names the new ONNX
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Task-specific completion outcomes are met.
- [ ] #2 Relevant verification, documentation, and pull-request gates have passed.
- [ ] #3 Implementation Notes, Modified Files, and the final summary reflect the delivered state.
- [ ] #4 The completing-tasks skill was invoked before task closure.
<!-- DOD:END -->

## Comments

<!-- COMMENTS:BEGIN -->
created: 2026-09-28 20:32
---
[board-autopilot] moved this task to `Ready` because every native dependency is `Done`. Its autonomy label is unchanged.
---

created: 2026-09-28 21:17
---
Claimed when the session's start prompt named it.
---

created: 2026-09-28 21:20
---
Operator start on 2026-09-28 14:17 MST found the condition unmet: labeler /api/images lists 1 labelled frigate_review_* image and 20 unlabelled frigate_event_* imports; deployed model unchanged (blue_package_plus_local_20260706_1305). Cleared the Done TASK-1565 dependency (one gate per task) and returned the task to Waiting with a date criterion (2026-10-06, roughly a week for the operator to label 20).
---

created: 2026-09-28 21:25
---
Replaced the date criterion with a prom criterion on frigate_labeler_labelled_event_images (>= 20), per operator: only data is a valid start criterion. The metric is delivered by TASK-1850.
---
<!-- COMMENTS:END -->
