"""The route tables: the model of each event, response, request and body the API names."""

from functools import reduce
from operator import or_
from typing import Any, NamedTuple

from pydantic import BaseModel

from starpulse.contracts.api.dto.dag import Runs
from starpulse.contracts.api.dto.errors import ApiError, SkillRefusal, StaleEdit, WindowTooLong
from starpulse.contracts.api.dto.harnesses import Harnesses, WindowState
from starpulse.contracts.api.dto.breaking_changes import BreakingChanges
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
from starpulse.contracts.api.dto.pages import DonePage, LaneHistory, LedgerChange, LedgerPage, Machines
from starpulse.contracts.api.dto.pulls import Pulls
from starpulse.contracts.api.dto.report import ContractReport, ReadyReport
from starpulse.contracts.api.dto.requests import (
    ArchiveRequest,
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
    RatingRequest,
    ReleaseRequest,
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
    Claimed,
    ClaimReleased,
    Completed,
    Created,
    CreatedEach,
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
    MovedEach,
    Parked,
    Rated,
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
    CostToGo,
    RunDiffs,
    Spend,
    TaskCostToGo,
    TaskDiff,
    TaskSpend,
)

#: Each `/api/events` event name and the model of its `data`.
EVENTS: dict[str, type[BaseModel]] = {
    "snapshot": Snapshot,
    "build": BuildEvent,
    "restarting": RestartingEvent,
    "stale": StaleEvent,
    "task": TaskDelta,
    "move": MoveDelta,
    "dags": DagsDelta,
    "pulls": PullsDelta,
    "claim": ClaimDelta,
    "verdict": VerdictDelta,
    "ledgers": LedgersDelta,
}
EVENTS["scheduler"] = SchedulerStatus

#: Each GET route's `200` body, by path; `/api/task/<id>` and `/api/ledger/<event>` by their prefix.
RESPONSES: dict[str, Any] = {
    "/api/snapshot": Snapshot,
    "/api/ledger/": LedgerPage,
    "/api/machines": Machines,
    "/api/harnesses": Harnesses,
    "/api/history-window": WindowState,
    "/api/doctor": ContractReport,
    "/api/ready": ReadyReport,
    "/api/flows": Snapshot,
    "/api/runs": Runs,
    "/api/task/": TaskRecord,
    "/api/moves/": TaskMoves,
    "/api/task-spend/": TaskSpend,
    "/api/task-diff/": TaskDiff,
    "/api/task-cost-to-go/": TaskCostToGo,
    "/api/task-records": TaskRecords,
    "/api/milestones": Milestones,
    "/api/milestones/": MilestoneShown,
    "/api/docs": Docs,
    "/api/docs/": DocShown,
    "/api/retired": RetiredTasks,
    "/api/history": LaneHistory | MachineHistory | TaskEventHistory,
    "/api/breaking-changes": BreakingChanges,
    "/api/pulls": Pulls,
    "/api/search": SearchResults,
    "/api/search/similar": SearchResults,
    "/api/scheduler": SchedulerStatus,
}

#: Each write route's request body.
REQUESTS: dict[str, type[BaseModel]] = {
    "/api/move": MoveRequest,
    "/api/start": StartRequest,
    "/api/edit": EditRequest,
    "/api/archive": ArchiveRequest,
    "/api/verdict": VerdictRequest,
    "/api/rating": RatingRequest,
    "/api/miss": MissRequest,
    "/api/restore": RestoreRequest,
    "/api/retire": RetireRequest,
    "/api/take-over": TakeOverRequest,
    "/api/retired/import": RetiredImportRequest,
    "/api/complete": CompleteRequest,
    "/api/reopen": ReopenRequest,
    "/api/claim": ClaimRequest,
    "/api/release": ReleaseRequest,
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
    "/api/scheduler": SchedulerRequest,
}

#: Every body a route may send, by route: what `encode` validates a body against.
BODIES: dict[str, Any] = {
    "error": ApiError,
    "snapshot": Snapshot,
    "ledger": LedgerPage | ApiError,
    "ledger_rows": LedgerChange,
    "machines": Machines | ApiError,
    "done": DonePage | ApiError,
    "history": LaneHistory | MachineHistory | TaskEventHistory | ApiError,
    "breaking_changes": BreakingChanges | ApiError,
    "pulls": Pulls | ApiError,
    "search": SearchResults | ApiError,
    "spend": Spend | ApiError | WindowTooLong,
    "taskSpend": TaskSpend | ApiError | WindowTooLong,
    "taskDiff": TaskDiff | ApiError | WindowTooLong,
    "taskCostToGo": TaskCostToGo | ApiError | WindowTooLong,
    "diff": RunDiffs | ApiError | WindowTooLong,
    "cost_to_go": CostToGo | ApiError | WindowTooLong,
    "trajectories": Trajectories | ApiError | WindowTooLong,
    "harnesses": Harnesses,
    "window": WindowState | ApiError,
    "scheduler": SchedulerStatus | ApiError,
    "doctor": ContractReport,
    "ready": ReadyReport,
    "runs": Runs,
    "task": TaskRecord | ApiError,
    "moves": TaskMoves | ApiError,
    "task_records": TaskRecords,
    "move": Moved | MovedEach | SkillRefusal | ApiError,
    "start": Started | SkillRefusal | ApiError,
    "edit": Edited | StaleEdit | SkillRefusal | ApiError,
    "archive": Archived | ArchivedEach | SkillRefusal | ApiError,
    "verdict": Judged | SkillRefusal | ApiError,
    "rating": Rated | ApiError,
    "restore": Restored | SkillRefusal | ApiError,
    "retire": Retired | SkillRefusal | ApiError,
    "take_over": TakenOver | ApiError,
    "retired": RetiredTasks | ApiError,
    "retired_import": RetiredImported | SkillRefusal | ApiError,
    "complete": Completed | SkillRefusal | ApiError,
    "reopen": Reopened | SkillRefusal | ApiError,
    "claim": Claimed | SkillRefusal | ApiError,
    "release": ClaimReleased | ApiError,
    "park": Parked | SkillRefusal | ApiError,
    "review": Reviewed | SkillRefusal | ApiError,
    "create": Created | CreatedEach | SkillRefusal | ApiError,
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
}


class Op(NamedTuple):
    """One method of one route: what it does, the model of the request body (a media type for a body no model
    describes), the models of its `200` answer and its query names; `media` is the type of the answer."""

    summary: str
    body: Any = None
    request: Any = None
    query: tuple[str, ...] = ()
    media: str = "application/json"


def _read(summary: str, kind: str | None = None, *query: str, media: str = "application/json") -> Op:
    return Op(summary, None if kind is None else BODIES[kind], None, query, media)


def _write(summary: str, kind: str, request: Any = None) -> Op:
    return Op(summary, BODIES[kind], request)


_STREAM = "text/event-stream"
_EVENTS = reduce(or_, EVENTS.values())

#: Every route the app serves outside the page's own files, by method and path: the model of each body it takes and
#: answers with. `tests/unit/contracts/test_openapi.py` fails when the app mounts a route this table lacks.
ROUTES: dict[tuple[str, str], Op] = {
    ("GET", "/api/events"): Op("Stream the board: a snapshot, then each change", _EVENTS, None, ("snapshot",), _STREAM),
    ("GET", "/api/held"): Op("Stream the columns with the tasks a session holds", None, None, ("assignee",), _STREAM),
    ("GET", "/api/lanes"): Op("Stream the columns, only the states named when given", None, None, ("state",), _STREAM),
    ("GET", "/api/events/body/{key}"): Op("A stored snapshot body by its key", BODIES["snapshot"] | ApiError),
    ("GET", "/api/snapshot"): _read("The board snapshot", "snapshot", "view"),
    ("GET", "/api/flows"): Op("The flows of the board", Snapshot),
    ("GET", "/api/ledger/{rest}/events"): Op("Stream a ledger's rows as they land", BODIES["ledger_rows"], media=_STREAM),
    ("GET", "/api/ledger/{rest}"): _read("A page of a ledger", "ledger", "before", "limit"),
    ("GET", "/api/doctor"): _read("The contract report", "doctor"),
    ("GET", "/api/ready"): _read("Whether the server is ready", "ready"),
    ("GET", "/api/runs"): _read("The workflow runs", "runs"),
    ("GET", "/api/machines"): _read("The machines and their lanes", "machines", "before", "limit", "open"),
    ("GET", "/api/done"): _read("A page of finished tasks", "done", "before", "limit"),
    ("GET", "/api/search"): _read(
        "Search tasks", "search", "before", "finished_within_days", "label", "limit", "q"
    ),
    ("GET", "/api/search/similar"): _read(
        "Tasks like a text", "search", "before", "finished_within_days", "label", "limit", "q"
    ),
    ("GET", "/api/harnesses"): _read("The harnesses and their windows", "harnesses"),
    ("GET", "/api/history"): _read("Lane, machine or task-event history", "history", "hours", "machine", "task"),
    ("GET", "/api/history-window"): _read("How many hours of history the store keeps", "window"),
    ("PUT", "/api/history-window"): _write("Set the history window", "window", WindowRequest),
    ("DELETE", "/api/history-window"): _write("Reset the history window to its default", "window"),
    ("GET", "/api/breaking-changes"): _read("The breaking changes", "breaking_changes", "open"),
    ("GET", "/api/task-spend/{id}"): _read("One task's spend", "taskSpend", "hours"),
    ("GET", "/api/task-diff/{id}"): _read("One task's diff", "taskDiff", "hours"),
    ("GET", "/api/task-cost-to-go/{id}"): _read("One task's cost to go", "taskCostToGo", "hours"),
    ("GET", "/api/task/{id}"): _read("One task", "task"),
    ("GET", "/api/moves/{id}"): _read("One task's moves", "moves"),
    ("GET", "/api/task-records"): _read("Task records, the ids named when given", "task_records", "ids"),
    ("GET", "/api/retired"): _read("Retired tasks", "retired", "before", "fields", "limit", "milestone", "task"),
    ("POST", "/api/move"): _write("Move tasks to a state", "move", MoveRequest),
    ("POST", "/api/start"): _write("Start a session on a task", "start", StartRequest),
    ("POST", "/api/edit"): _write("Edit a task", "edit", EditRequest),
    ("POST", "/api/archive"): _write("Archive tasks", "archive", ArchiveRequest),
    ("POST", "/api/verdict"): _write("Record a verdict", "verdict", VerdictRequest),
    ("POST", "/api/rating"): _write("Record a rating", "rating", RatingRequest),
    ("POST", "/api/miss"): _write("Record a miss", "verdict", MissRequest),
    ("POST", "/api/restore"): _write("Restore an archived task", "restore", RestoreRequest),
    ("POST", "/api/take-over"): _write("Take a session over", "take_over", TakeOverRequest),
    ("POST", "/api/retire"): _write("Retire a task", "retire", RetireRequest),
    ("POST", "/api/retired/import"): _write("Import retired tasks", "retired_import", RetiredImportRequest),
    ("POST", "/api/claim"): _write("Claim a task", "claim", ClaimRequest),
    ("POST", "/api/release"): _write("Release a claim", "release", ReleaseRequest),
    ("POST", "/api/park"): _write("Park a task", "park", ParkRequest),
    ("POST", "/api/review"): _write("Record a review", "review", ReviewRequest),
    ("POST", "/api/complete"): _write("Complete a task", "complete", CompleteRequest),
    ("POST", "/api/reopen"): _write("Reopen a task", "reopen", ReopenRequest),
    ("POST", "/api/tasks"): _write("Create tasks", "create", CreateRequest),
    ("GET", "/api/milestones/{id}"): _read("One milestone", "milestone"),
    ("GET", "/api/milestones"): _read("The milestones", "milestones"),
    ("POST", "/api/milestones"): _write("Create a milestone", "milestone_create", MilestoneCreateRequest),
    ("POST", "/api/milestones/edit"): _write("Edit a milestone", "milestone_edit", MilestoneEditRequest),
    ("POST", "/api/milestones/archive"): _write("Archive a milestone", "milestone_archive", MilestoneArchiveRequest),
    ("GET", "/api/docs/{id}"): _read("One doc", "doc"),
    ("GET", "/api/docs"): _read("The docs, the ids named when given", "docs", "ids"),
    ("POST", "/api/docs"): _write("Create a doc", "doc_create", DocCreateRequest),
    ("POST", "/api/docs/edit"): _write("Edit a doc", "doc_edit", DocEditRequest),
    ("POST", "/api/docs/archive"): _write("Archive a doc", "doc_archive", DocArchiveRequest),
    ("POST", "/api/docs/restore"): _write("Restore an archived doc", "doc_restore", DocRestoreRequest),
    ("POST", "/api/run/{name}"): _write("Run a workflow", "run"),
    ("POST", "/api/runs/{instance}/{workflow}/rerun"): _write("Rerun a workflow run", "run"),
    ("POST", "/api/machine-events"): _write("Ingest CloudEvents", "ingest", "application/cloudevents-batch+json"),
    ("POST", "/api/temporal-completion"): _write("Ingest a Temporal completion", "ingest", "application/json"),
    ("POST", "/api/webhook"): _write("Ingest a GitHub webhook", "ingest", "application/json"),
    ("GET", "/api/scheduler"): _read("The scheduler's state", "scheduler"),
    ("PUT", "/api/scheduler"): _write("Switch the scheduler on or off", "scheduler", SchedulerRequest),
    ("GET", "/api/pulls"): _read("Pull requests", "pulls", "bodies", "body_contains", "number", "repo", "state", "task"),
    ("GET", "/api/openapi"): Op("This document"),
    ("GET", "/metrics"): _read("Prometheus metrics", media="text/plain"),
    ("GET", "/autopilot-log"): _read("The autopilot log"),
    ("GET", "/actor-view"): _read("What the task actor holds, one task's when named", None, "task"),
    ("GET", "/swagger"): Op("The Swagger page of this document", media="text/html"),
}
