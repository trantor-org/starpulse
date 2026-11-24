"""The JSON Schema of every body, as `api.schema.json` holds it."""

import json
from pathlib import Path
from typing import Any

from pydantic.json_schema import GenerateJsonSchema

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.dag import Runs
from starpulse.contracts.api.dto.errors import ApiError, SkillRefusal, StaleEdit, WindowTooLong
from starpulse.contracts.api.dto.harnesses import Harnesses, WindowState
from starpulse.contracts.api.dto.health import MachineHistory, TaskEventHistory
from starpulse.contracts.api.dto.milestones import (
    Docs,
    DocShown,
    Milestones,
    MilestoneShown,
    RetiredTasks,
    TaskMoves,
    TaskRecord,
    TaskRecords,
)
from starpulse.contracts.api.dto.pages import DonePage, LaneHistory, LedgerChange, LedgerPage, MachineDetail, Machines
from starpulse.contracts.api.dto.graphql import GraphqlRequest, GraphqlResponse, ViewShown
from starpulse.contracts.api.dto.pulls import Pulls
from starpulse.contracts.api.dto.report import ContractReport, ReadyReport
from starpulse.contracts.api.dto.requests import (
    ArchiveRequest,
    CompleteRequest,
    CreateRequest,
    DispatchRequest,
    DocCreateRequest,
    DocListRequest,
    DocPutRequest,
    EditRequest,
    MilestoneCreateRequest,
    MachineListRequest,
    MilestoneListRequest,
    MilestonePutRequest,
    MissRequest,
    MoveRequest,
    ParkRequest,
    ReopenRequest,
    RestoreRequest,
    RetiredImportRequest,
    RetireRequest,
    ReviewRequest,
    SchedulerRequest,
    StartRequest,
    TakeOverRequest,
    VerdictRequest,
    WindowRequest,
)
from starpulse.contracts.api.dto.results import (
    Accepted,
    Archived,
    ArchivedEach,
    Completed,
    Created,
    CreatedEach,
    Dispatched,
    DocArchived,
    DocCreated,
    DocEdited,
    Edited,
    Judged,
    MilestoneArchived,
    MilestoneCreated,
    MilestoneEdited,
    Moved,
    MovedEach,
    Parked,
    Reopened,
    Restored,
    Retired,
    RetiredImported,
    Reviewed,
    RunStarted,
    Started,
    TakenOver,
)
from starpulse.contracts.api.dto.scheduler import SchedulerStatus
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
    StaleEvent,
    TaskDelta,
    VerdictDelta,
)
from starpulse.contracts.api.dto.trajectories import Trajectories
from starpulse.contracts.api.dto.transitions import (
    Spend,
    TaskSpend,
)


class ApiContract(_Api):
    """The root of `api.schema.json`: every body as a property, so the generated types name each one."""

    snapshot: Snapshot
    events: list[
        TaskDelta | MoveDelta | DagsDelta | PullsDelta | ClaimDelta | VerdictDelta | LedgersDelta | SchedulerStatus
    ]
    build: BuildEvent
    restarting: RestartingEvent
    stale: StaleEvent
    ledger: LedgerPage
    ledgerChange: LedgerChange
    donePage: DonePage
    machines: Machines
    machineDetail: MachineDetail
    laneHistory: LaneHistory
    machineHistory: MachineHistory
    taskEventHistory: TaskEventHistory
    pulls: Pulls
    graphqlResponse: GraphqlResponse
    viewShown: ViewShown
    searchResults: SearchResults
    spend: Spend
    taskSpend: TaskSpend
    trajectories: Trajectories
    harnesses: Harnesses
    windowState: WindowState
    schedulerStatus: SchedulerStatus
    contractReport: ContractReport
    readyReport: ReadyReport
    runs: Runs
    taskRecord: TaskRecord
    taskMoves: TaskMoves
    taskRecords: TaskRecords
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
        | MissRequest
        | RestoreRequest
        | RetireRequest
        | TakeOverRequest
        | RetiredImportRequest
        | CompleteRequest
        | ReopenRequest
        | DispatchRequest
        | ParkRequest
        | ReviewRequest
        | CreateRequest
        | MilestoneCreateRequest
        | MachineListRequest
        | MilestoneListRequest
        | MilestonePutRequest
        | DocCreateRequest
        | DocListRequest
        | DocPutRequest
        | WindowRequest
        | SchedulerRequest
        | GraphqlRequest
    ]
    answers: list[
        Moved
        | MovedEach
        | Edited
        | Archived
        | ArchivedEach
        | Judged
        | Restored
        | Retired
        | TakenOver
        | RetiredImported
        | Completed
        | Reopened
        | Dispatched
        | Parked
        | Reviewed
        | Created
        | CreatedEach
        | MilestoneCreated
        | MilestoneEdited
        | MilestoneArchived
        | DocCreated
        | DocEdited
        | DocArchived
        | Started
        | RunStarted
        | Accepted
        | ApiError
        | SkillRefusal
        | StaleEdit
        | WindowTooLong
    ]


#: Where the schema is written: beside `machine.schema.json` in `schemas/`, with the adapter contracts, which ship.
SCHEMA = Path(__file__).parents[2] / "schemas" / "api.schema.json"


class _Generator(GenerateJsonSchema):
    """Titles only models: a field title would make json-schema-to-typescript name a type for each field."""

    def field_title_should_be_set(self, schema: Any) -> bool:
        return False


def schema() -> str:
    """The JSON Schema of every body, as the file `SCHEMA` holds it."""
    document = ApiContract.model_json_schema(by_alias=True, schema_generator=_Generator)
    return json.dumps(document, indent=2, sort_keys=True) + "\n"
