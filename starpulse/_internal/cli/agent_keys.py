"""The output keys each agent verb documents in `starpulse help --agent`, and the snapshot keys a server must answer."""

from __future__ import annotations

SNAPSHOT_KEYS = (
    "graphs",
    "flows",
    "dags",
    "pools",
    "pulls",
    "mergeStrip",
    "mergePins",
    "machinePage",
    "machineStrip",
    "claims",
    "insights",
    "settled",
    "cold_done",
    "error",
    "cues",
    "domains",
    "boardUrl",
    "hint",
    "capabilities",
    "reading",
    "now",
)


LEVEL_KEYS = (
    "now",
    "window_s",
    "history_s",
    "machine",
    "goal",
    "wip",
    "throughput",
    "time_in_state",
    "aging",
    "orbit",
    "sources",
)


TRAJECTORY_KEYS = (
    "now",
    "window_s",
    "history_s",
    "machine",
    "goal",
    "ended",
    "variants",
    "norm",
    "outliers",
    "chain",
    "betweenness",
    "bottleneck",
    "loops",
    "runs",
)


GATE_KEYS = ("now", "window_s", "history_s", "machine", "goal", "ended", "gates", "runs")


FORECAST_KEYS = ("now", "window_s", "history_s", "machine", "goal", "ended", "forecast", "calibration")


WHAT_IF_KEYS = (
    "now",
    "window_s",
    "history_s",
    "machine",
    "goal",
    "ended",
    "from",
    "to",
    "p",
    "was",
    "n",
    "start",
    "p_goal",
    "expected_days",
    "chain",
)


HEALTH_KEYS = ("now", "window_s", "stuck_after_s", "states", "throughput", "stuck", "warnings")


STEP_KEYS = ("now", "window_s", "steps")


TRANSITION_KEYS = ("now", "window_s", "transitions")


CELL_KEYS = ("now", "window_s", "cells")


GRAPH_KEYS = ("now", "window_s", "graph")


STAGE_KEYS = ("now", "window_s", "stages")


DIFF_KEYS = ("now", "window_s", "diff")


TASK_KEYS = (
    "id",
    "title",
    "lane",
    "assignee",
    "holder",
    "milestone",
    "type",
    "labels",
    "dependencies",
    "waiting_on",
    "criteria",
    "pause_reason",
    "prs",
    "moves",
    "description",
)


MOVE_KEYS = ("ok", "task", "to", "reason", "skill", "advice")


CLAIM_KEYS = ("ok", "task", "to", "holder", "reason", "skill")


LIFECYCLE_KEYS = ("ok", "task", "to", "reason", "skill")


MILESTONE_KEYS = ("id", "title", "outcome", "specs", "adrs", "retro", "description")


DOC_KEYS = ("id", "title", "type", "created_date", "updated_date", "path", "body")
