"""The JSON Schema of every body, as `api.schema.json` holds it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic.json_schema import GenerateJsonSchema

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.errors import ApiError, SkillRefusal, StaleEdit, WindowTooLong
from starpulse.contracts.api.dto.scheduler import SchedulerStatus
from starpulse.contracts.api.dto.harnesses import Harnesses, WindowState
from starpulse.contracts.api.dto.health import Health, MachineHistory, Sessions, SessionSteps
from starpulse.contracts.api.dto.milestones import Docs, DocShown, Milestones, MilestoneShown, RetiredTasks, TaskRecord
from starpulse.contracts.api.dto.missed import MissedLoads, TraceClusters
from starpulse.contracts.api.dto.pages import LaneHistory, LedgerChange, LedgerPage, Machines
from starpulse.contracts.api.dto.pulls import Pulls
from starpulse.contracts.api.dto.report import ContractReport
from starpulse.contracts.api.dto.requests import (
    ArchiveRequest,
    SchedulerRequest,
    ClaimRequest,
    CompleteRequest,
    CreateRequest,
    DocArchiveRequest,
    DocCreateRequest,
    DocEditRequest,
    DocRestoreRequest,
    EditRequest,
    MilestoneArchiveRequest,
    MilestoneCreateRequest,
    MilestoneEditRequest,
    MissRequest,
    MoveRequest,
    ParkRequest,
    RestoreRequest,
    RetiredImportRequest,
    RetireRequest,
    RatingRequest,
    ReviewRequest,
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
    Judged,
    MilestoneArchived,
    MilestoneCreated,
    MilestoneEdited,
    Moved,
    Parked,
    Rated,
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
    LedgersDelta,
    MoveDelta,
    PullsDelta,
    RestartingEvent,
    Snapshot,
    TaskDelta,
)
from starpulse.contracts.api.dto.trajectories import Trajectories
from starpulse.contracts.api.dto.transitions import Cells, CostToGo, FlowGraph, RunDiffs, SubStages, Transitions


class ApiContract(_Api):
    """The root of `api.schema.json`: every body as a property, so the generated types name each one."""

    snapshot: Snapshot
    events: list[
        TaskDelta | MoveDelta | DagsDelta | PullsDelta | ClaimDelta | LedgersDelta | SchedulerStatus
    ]
    build: BuildEvent
    restarting: RestartingEvent
    ledger: LedgerPage
    ledgerChange: LedgerChange
    machines: Machines
    laneHistory: LaneHistory
    machineHistory: MachineHistory
    pulls: Pulls
    searchResults: SearchResults
    health: Health
    sessions: Sessions
    sessionSteps: SessionSteps
    transitions: Transitions
    cells: Cells
    graph: FlowGraph
    stages: SubStages
    diff: RunDiffs
    costToGo: CostToGo
    missedLoads: MissedLoads
    traceClusters: TraceClusters
    trajectories: Trajectories
    harnesses: Harnesses
    windowState: WindowState
    schedulerStatus: SchedulerStatus
    contractReport: ContractReport
    taskRecord: TaskRecord
    milestones: Milestones
    milestoneShown: MilestoneShown
    docs: Docs
    docShown: DocShown
    retiredTasks: RetiredTasks
    requests: list[
        MoveRequest
        | StartRequest
        | EditRequest
        | ArchiveRequest
        | VerdictRequest
        | RatingRequest
        | MissRequest
        | RestoreRequest
        | RetireRequest
        | RetiredImportRequest
        | CompleteRequest
        | ClaimRequest
        | ParkRequest
        | ReviewRequest
        | CreateRequest
        | MilestoneCreateRequest
        | MilestoneEditRequest
        | MilestoneArchiveRequest
        | DocCreateRequest
        | DocEditRequest
        | DocArchiveRequest
        | DocRestoreRequest
        | WindowRequest
        | SchedulerRequest
    ]
    answers: list[
        Moved
        | Edited
        | Archived
        | Judged
        | Rated
        | Restored
        | Retired
        | RetiredImported
        | Completed
        | Claimed
        | Parked
        | Reviewed
        | Created
        | MilestoneCreated
        | MilestoneEdited
        | MilestoneArchived
        | DocCreated
        | DocEdited
        | DocArchived
        | DocRestored
        | Started
        | RunStarted
        | Accepted
        | ApiError
        | SkillRefusal
        | StaleEdit
        | WindowTooLong
    ]


#: Where the schema is written: beside `machine.schema.json`, not among the adapter contracts' `schemas/`, which ship.
SCHEMA = Path(__file__).parents[2] / "api.schema.json"


class _Generator(GenerateJsonSchema):
    """Titles only models: a field title would make json-schema-to-typescript name a type for each field."""

    def field_title_should_be_set(self, schema: Any) -> bool:
        return False


def schema() -> str:
    """The JSON Schema of every body, as the file `SCHEMA` holds it."""
    document = ApiContract.model_json_schema(by_alias=True, schema_generator=_Generator)
    return json.dumps(document, indent=2, sort_keys=True) + "\n"
