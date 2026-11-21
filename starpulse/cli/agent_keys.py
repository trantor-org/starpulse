"""The output keys each agent verb documents in `starpulse help --agent`, and the snapshot keys a server must answer."""

SNAPSHOT_KEYS = (
    "graphs",
    "flows",
    "dags",
    "pools",
    "cpu",
    "pulls",
    "mergeStrip",
    "mergePins",
    "machinePage",
    "machineStrip",
    "claims",
    "settled",
    "move_sets",
    "milestone_done",
    "archived_today",
    "ratings",
    "interactive",
    "roles",
    "error",
    "cues",
    "domains",
    "boardUrl",
    "capabilities",
    "reading",
    "now",
)

# What makes a document a StarPulse snapshot; any other key may come or go between releases.
SNAPSHOT_IDENTITY_KEYS = ("graphs", "flows", "machinePage", "now")


HEALTH_KEYS = ("now", "window_s", "stuck_after_s", "states", "throughput", "stuck", "warnings")


LIVENESS_KEYS = ("now", "window_s", "stalled_after_s", "tasks", "review", "in_progress_s", "slot_s", "slots", "stages", "stalls")


STEP_KEYS = ("now", "window_s", "steps")


TRANSITION_KEYS = ("now", "window_s", "transitions")
SPEND_KEYS = ("now", "window_s", "spend")


CELL_KEYS = ("now", "window_s", "cells")
ESTIMATE_KEYS = ("now", "window_s", "estimates")
SCORE_KEYS = ("now", "window_s", "scores", "verdicts")
VERDICT_KEYS = ("kind", "size", "baseline", "profile", "n", "baseline_n", "verdict", "p_non_inferior", "p_worse")


GRAPH_KEYS = ("now", "window_s", "graph")


STAGE_KEYS = ("now", "window_s", "stages")


DIFF_KEYS = ("now", "window_s", "diff")


TASK_KEYS = (
    "id",
    "title",
    "lane",
    "phase",
    "substate",
    "skill",
    "interactive",
    "done_at",
    "profile",
    "assignee",
    "milestone",
    "type",
    "impact",
    "urgency",
    "labels",
    "dependencies",
    "waiting_on",
    "criteria",
    "pause_reason",
    "readable",
    "source",
    "verify_plan",
    "prs",
    "moves",
    "rating",
    "released",
    "description",
)


MOVE_KEYS = ("ok", "task", "to", "reason", "skill", "advice")


CLAIM_KEYS = ("ok", "task", "to", "assignee", "reason", "skill")


RELEASE_KEYS = ("ok", "task", "to", "releasedFrom", "reason", "skill")


LIFECYCLE_KEYS = ("ok", "task", "to", "reason", "skill")


MILESTONE_KEYS = ("id", "title", "outcome", "specs", "adrs", "retro", "description")


PULL_KEYS = (
    "repo",
    "number",
    "state",
    "isDraft",
    "mergeable",
    "baseRefName",
    "headRefOid",
    "body",
    "checks",
    "requiredChecks",
    "threads",
    "unresolvedThreads",
    "headRefName",
    "updatedAt",
    "mergedAt",
    "mergeSha",
    "fetchedAt",
    "files",
)


DOC_KEYS = ("id", "title", "type", "created_date", "updated_date", "path", "body")
