"""The route tables: the model of each event, response, request and body the API names."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from starpulse.contracts.adapters import Finding
from starpulse.contracts.api.dto.errors import ApiError, SkillRefusal, StaleEdit, WindowTooLong
from starpulse.contracts.api.dto.forwarding import AutopilotStatus, ForwardingStatus, ForwardingUnconfigured
from starpulse.contracts.api.dto.harnesses import Harnesses, WindowState
from starpulse.contracts.api.dto.health import Health, MachineHistory, Sessions, SessionSteps
from starpulse.contracts.api.dto.level import Level
from starpulse.contracts.api.dto.milestones import Docs, DocShown, Milestones, MilestoneShown, RetiredTasks, TaskRecord
from starpulse.contracts.api.dto.missed import MissedLoads, TraceClusters
from starpulse.contracts.api.dto.pages import DonePage, LaneHistory, LedgerChange, LedgerPage, Machines
from starpulse.contracts.api.dto.pulls import Pulls
from starpulse.contracts.api.dto.report import ContractReport
from starpulse.contracts.api.dto.requests import (
    ArchiveRequest,
    AutopilotRequest,
    ClaimRequest,
    CompleteRequest,
    CreateRequest,
    DocArchiveRequest,
    DocCreateRequest,
    DocEditRequest,
    DocRestoreRequest,
    EditRequest,
    ForwardingRequest,
    ForwardRequest,
    MilestoneArchiveRequest,
    MilestoneCreateRequest,
    MilestoneEditRequest,
    MissRequest,
    MoveRequest,
    ParkRequest,
    RestoreRequest,
    RetiredImportRequest,
    RetireRequest,
    ReviewRequest,
    RunEventRequest,
    StartRequest,
    VerdictRequest,
    WindowRequest,
)
from starpulse.contracts.api.dto.results import (
    Accepted,
    Archived,
    Claimed,
    Completed,
    Created,
    DocArchived,
    DocCreated,
    DocEdited,
    DocRestored,
    Edited,
    ForwardAccepted,
    InsightPosted,
    InsightRetracted,
    Judged,
    MilestoneArchived,
    MilestoneCreated,
    MilestoneEdited,
    Moved,
    Parked,
    Restored,
    Retired,
    RetiredImported,
    Reviewed,
    RunStarted,
    Started,
)
from starpulse.contracts.api.dto.search import SearchResults
from starpulse.contracts.api.dto.snapshot import (
    BuildEvent,
    ClaimDelta,
    DagsDelta,
    InsightDelta,
    LedgersDelta,
    MoveDelta,
    PullsDelta,
    RestartingEvent,
    Snapshot,
    TaskDelta,
)
from starpulse.contracts.api.dto.trajectories import Trajectories
from starpulse.contracts.api.dto.transitions import Cells, CostToGo, FlowGraph, RunDiffs, SubStages, Transitions
from starpulse.contracts.api.dto.what_if import WhatIf

#: Each `/api/events` event name and the model of its `data`.
EVENTS: dict[str, type[BaseModel]] = {
    "snapshot": Snapshot,
    "build": BuildEvent,
    "restarting": RestartingEvent,
    "task": TaskDelta,
    "move": MoveDelta,
    "dags": DagsDelta,
    "pulls": PullsDelta,
    "claim": ClaimDelta,
    "ledgers": LedgersDelta,
    "insight": InsightDelta,
}
EVENTS["autopilot"] = AutopilotStatus
EVENTS["level"] = Level
EVENTS["forwarding"] = ForwardingStatus

#: Each GET route's `200` body, by path; `/api/task/<id>` and `/api/ledger/<event>` by their prefix.
RESPONSES: dict[str, Any] = {
    "/api/snapshot": Snapshot,
    "/api/ledger/": LedgerPage,
    "/api/machines": Machines,
    "/api/analytics/health": Health,
    "/api/analytics/sessions": Sessions,
    "/api/analytics/steps": SessionSteps,
    "/api/analytics/transitions": Transitions,
    "/api/analytics/cells": Cells,
    "/api/analytics/graph": FlowGraph,
    "/api/analytics/stages": SubStages,
    "/api/analytics/diff": RunDiffs,
    "/api/analytics/cost-to-go": CostToGo,
    "/api/analytics/missed-loads": MissedLoads,
    "/api/analytics/trace-clusters": TraceClusters,
    "/api/level": Level,
    "/api/level/trajectories": Trajectories,
    "/api/level/what-if": WhatIf,
    "/api/harnesses": Harnesses,
    "/api/history-window": WindowState,
    "/api/doctor": ContractReport,
    "/api/task/": TaskRecord,
    "/api/milestones": Milestones,
    "/api/milestones/": MilestoneShown,
    "/api/docs": Docs,
    "/api/docs/": DocShown,
    "/api/retired": RetiredTasks,
    "/api/history": LaneHistory | MachineHistory,
    "/api/pulls": Pulls,
    "/api/search": SearchResults,
    "/api/forwarding": ForwardingStatus | ForwardingUnconfigured,
    "/api/autopilot": AutopilotStatus,
}

#: Each write route's request body.
REQUESTS: dict[str, type[BaseModel]] = {
    "/api/move": MoveRequest,
    "/api/start": StartRequest,
    "/api/edit": EditRequest,
    "/api/archive": ArchiveRequest,
    "/api/verdict": VerdictRequest,
    "/api/miss": MissRequest,
    "/api/restore": RestoreRequest,
    "/api/retire": RetireRequest,
    "/api/retired/import": RetiredImportRequest,
    "/api/complete": CompleteRequest,
    "/api/claim": ClaimRequest,
    "/api/park": ParkRequest,
    "/api/review": ReviewRequest,
    "/api/tasks": CreateRequest,
    "/api/milestones": MilestoneCreateRequest,
    "/api/milestones/edit": MilestoneEditRequest,
    "/api/milestones/archive": MilestoneArchiveRequest,
    "/api/docs": DocCreateRequest,
    "/api/docs/edit": DocEditRequest,
    "/api/docs/archive": DocArchiveRequest,
    "/api/docs/restore": DocRestoreRequest,
    "/api/history-window": WindowRequest,
    "/api/forwarding": ForwardingRequest,
    "/api/autopilot": AutopilotRequest,
    "/api/runs/events": RunEventRequest,
    "/api/forward": ForwardRequest,
    "/api/insights": Finding,
}

#: Every body a route may send, by route: what `encode` validates a body against.
BODIES: dict[str, Any] = {
    "error": ApiError,
    "snapshot": Snapshot,
    "ledger": LedgerPage | ApiError,
    "ledger_rows": LedgerChange,
    "machines": Machines | ApiError,
    "done": DonePage | ApiError,
    "history": LaneHistory | MachineHistory | ApiError,
    "pulls": Pulls | ApiError,
    "search": SearchResults | ApiError,
    "health": Health | ApiError,
    "sessions": Sessions | ApiError | WindowTooLong,
    "session_steps": SessionSteps | ApiError | WindowTooLong,
    "transitions": Transitions | ApiError | WindowTooLong,
    "cells": Cells | ApiError | WindowTooLong,
    "graph": FlowGraph | ApiError | WindowTooLong,
    "stages": SubStages | ApiError | WindowTooLong,
    "diff": RunDiffs | ApiError | WindowTooLong,
    "cost_to_go": CostToGo | ApiError | WindowTooLong,
    "missed_loads": MissedLoads | ApiError | WindowTooLong,
    "trace_clusters": TraceClusters | ApiError | WindowTooLong,
    "level": Level | ApiError | WindowTooLong,
    "trajectories": Trajectories | ApiError | WindowTooLong,
    "what_if": WhatIf | ApiError | WindowTooLong,
    "harnesses": Harnesses,
    "window": WindowState | ApiError,
    "forwarding": ForwardingStatus | ForwardingUnconfigured | ApiError,
    "autopilot": AutopilotStatus | ApiError,
    "doctor": ContractReport,
    "task": TaskRecord | ApiError,
    "move": Moved | SkillRefusal | ApiError,
    "start": Started | SkillRefusal | ApiError,
    "edit": Edited | StaleEdit | SkillRefusal | ApiError,
    "archive": Archived | SkillRefusal | ApiError,
    "verdict": Judged | SkillRefusal | ApiError,
    "restore": Restored | SkillRefusal | ApiError,
    "retire": Retired | SkillRefusal | ApiError,
    "retired": RetiredTasks | ApiError,
    "retired_import": RetiredImported | SkillRefusal | ApiError,
    "complete": Completed | SkillRefusal | ApiError,
    "claim": Claimed | SkillRefusal | ApiError,
    "park": Parked | SkillRefusal | ApiError,
    "review": Reviewed | SkillRefusal | ApiError,
    "create": Created | SkillRefusal | ApiError,
    "milestones": Milestones | ApiError,
    "milestone": MilestoneShown | ApiError,
    "milestone_create": MilestoneCreated | SkillRefusal | ApiError,
    "milestone_edit": MilestoneEdited | SkillRefusal | ApiError,
    "milestone_archive": MilestoneArchived | SkillRefusal | ApiError,
    "docs": Docs | ApiError,
    "doc": DocShown | ApiError,
    "doc_create": DocCreated | SkillRefusal | ApiError,
    "doc_edit": DocEdited | SkillRefusal | ApiError,
    "doc_archive": DocArchived | SkillRefusal | ApiError,
    "doc_restore": DocRestored | SkillRefusal | ApiError,
    "run": RunStarted | ApiError,
    "ingest": Accepted | ApiError,
    "forward": ForwardAccepted | ApiError,
    "insight": InsightPosted | InsightRetracted | ApiError,
}
