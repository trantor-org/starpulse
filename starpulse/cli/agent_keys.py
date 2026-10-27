"""The output keys each agent verb documents in `starpulse help --agent`, and the snapshot keys a server must answer."""

from __future__ import annotations

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
    "cold_done",
    "ratings",
    "interactive",
    "roles",
    "error",
    "cues",
    "domains",
    "boardUrl",
    "hint",
    "capabilities",
    "reading",
    "now",
)


HEALTH_KEYS = ("now", "window_s", "stuck_after_s", "states", "throughput", "stuck", "warnings")


STEP_KEYS = ("now", "window_s", "steps")


TRANSITION_KEYS = ("now", "window_s", "transitions")


CELL_KEYS = ("now", "window_s", "cells")
SCORE_KEYS = ("now", "window_s", "scores", "verdicts")


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
    "labels",
    "dependencies",
    "waiting_on",
    "criteria",
    "pause_reason",
    "prs",
    "moves",
    "rating",
    "released",
    "description",
)


MOVE_KEYS = ("ok", "task", "to", "reason", "skill", "advice")


CLAIM_KEYS = ("ok", "task", "to", "assignee", "reason", "skill")


LIFECYCLE_KEYS = ("ok", "task", "to", "reason", "skill")


MILESTONE_KEYS = ("id", "title", "outcome", "specs", "adrs", "retro", "description")


DOC_KEYS = ("id", "title", "type", "created_date", "updated_date", "path", "body")
