"""The route tables: the model of each event, response, request and body the API names."""

from functools import reduce
from operator import or_
from typing import Any, NamedTuple

from pydantic import BaseModel

from starpulse.contracts.api.dto.admin import AdminState
from starpulse.contracts.api.dto.dag import Runs
from starpulse.contracts.api.dto.errors import ApiError, SkillRefusal, StaleEdit, WindowTooLong
from starpulse.contracts.api.dto.graphql import GraphqlRequest, GraphqlResponse, ViewShown
from starpulse.contracts.api.dto.harnesses import Harnesses, WindowState
from starpulse.contracts.api.dto.health import MachineHistory, TaskEventHistory
from starpulse.contracts.api.dto.milestones import (
    Docs,
    DocShown,
    Milestones,
    MilestoneShown,
    RetiredTasks,
    TaskRecord,
    TaskRecords,
)
from starpulse.contracts.api.dto.pages import DonePage, LaneHistory, LedgerChange, LedgerPage, MachineDetail, Machines
from starpulse.contracts.api.dto.pulls import Pulls
from starpulse.contracts.api.dto.report import ContractReport, ReadyReport
from starpulse.contracts.api.dto.requests import (
    AdminRequest,
    ArchiveRequest,
    CompleteRequest,
    CreateRequest,
    DispatchRequest,
    DocCreateRequest,
    DocListRequest,
    DocPutRequest,
    EditRequest,
    MachineCreateRequest,
    MachineListRequest,
    MachinePutRequest,
    MilestoneCreateRequest,
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
    StartRequest,
    TakeOverRequest,
    TaskPutRequest,
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
    MachineRetired,
    MachineWritten,
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
    "/api/machines/": MachineDetail,
    "/api/harnesses": Harnesses,
    "/api/history-window": WindowState,
    "/api/doctor": ContractReport,
    "/api/health": ReadyReport,
    "/api/flows": Snapshot,
    "/api/runs": Runs,
    "/api/task/": TaskRecord,
    "/api/task-records": TaskRecords,
    "/api/milestones/": MilestoneShown,
    "/api/docs/": DocShown,
    "/api/retired": RetiredTasks,
    "/api/history": LaneHistory | MachineHistory | TaskEventHistory,
    "/api/pulls": Pulls,
    "/api/search": SearchResults,
    "/api/search/similar": SearchResults,
    "/api/views/": ViewShown,
    "/api/admin": AdminState,
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
    "/api/take-over": TakeOverRequest,
    "/api/retired/import": RetiredImportRequest,
    "/api/complete": CompleteRequest,
    "/api/reopen": ReopenRequest,
    "/api/dispatch": DispatchRequest,
    "/api/park": ParkRequest,
    "/api/review": ReviewRequest,
    "/api/tasks": CreateRequest,
    "/api/machines": MachineCreateRequest,
    "/api/machines/{name}": MachinePutRequest,
    "/api/tasks/{id}": TaskPutRequest,
    "/api/milestones": MilestoneCreateRequest,
    "/api/milestones/{id}": MilestonePutRequest,
    "/api/docs": DocCreateRequest,
    "/api/docs/{id}": DocPutRequest,
    "/api/history-window": WindowRequest,
    "/graphql": GraphqlRequest,
    "/api/admin": AdminRequest,
}

#: Each list route's request body: a POST to a path a PUT also writes, which `REQUESTS` names.
LISTS: dict[str, type[BaseModel]] = {
    "/api/machines": MachineListRequest,
    "/api/milestones": MilestoneListRequest,
    "/api/docs": DocListRequest,
}

#: Every body a route may send, by route: what `encode` validates a body against.
BODIES: dict[str, Any] = {
    "error": ApiError,
    "snapshot": Snapshot,
    "ledger": LedgerPage | ApiError,
    "ledger_rows": LedgerChange,
    "machines": Machines | ApiError,
    "machine": MachineDetail | ApiError,
    "machine_create": MachineWritten | ApiError,
    "machine_put": MachineWritten | ApiError,
    "machine_retire": MachineRetired | ApiError,
    "done": DonePage | ApiError,
    "history": LaneHistory | MachineHistory | TaskEventHistory | ApiError,
    "pulls": Pulls | ApiError,
    "search": SearchResults | ApiError,
    "spend": Spend | ApiError | WindowTooLong,
    "trajectories": Trajectories | ApiError | WindowTooLong,
    "harnesses": Harnesses,
    "window": WindowState | ApiError,
    "admin": AdminState | ApiError,
    "doctor": ContractReport,
    "ready": ReadyReport,
    "runs": Runs,
    "task": TaskRecord | ApiError,
    "task_records": TaskRecords,
    "move": Moved | MovedEach | SkillRefusal | ApiError,
    "start": Started | SkillRefusal | ApiError,
    "edit": Edited | StaleEdit | SkillRefusal | ApiError,
    "archive": Archived | ArchivedEach | SkillRefusal | ApiError,
    "verdict": Judged | SkillRefusal | ApiError,
    "restore": Restored | SkillRefusal | ApiError,
    "retire": Retired | SkillRefusal | ApiError,
    "take_over": TakenOver | ApiError,
    "retired": RetiredTasks | ApiError,
    "retired_import": RetiredImported | SkillRefusal | ApiError,
    "complete": Completed | SkillRefusal | ApiError,
    "reopen": Reopened | SkillRefusal | ApiError,
    "dispatch": Dispatched | ApiError,
    "park": Parked | SkillRefusal | ApiError,
    "review": Reviewed | SkillRefusal | ApiError,
    "create": Created | CreatedEach | SkillRefusal | ApiError,
    "task_put": Edited | StaleEdit | Restored | Reopened | TakenOver | SkillRefusal | ApiError,
    "task_delete": Archived | SkillRefusal | ApiError,
    "milestones": Milestones | ApiError,
    "milestone": MilestoneShown | ApiError,
    "milestone_create": MilestoneCreated | SkillRefusal | ApiError,
    "milestone_put": MilestoneEdited | SkillRefusal | ApiError,
    "milestone_archive": MilestoneArchived | SkillRefusal | ApiError,
    "docs": Docs | ApiError,
    "doc": DocShown | ApiError,
    "doc_create": DocCreated | SkillRefusal | ApiError,
    "doc_put": DocEdited | SkillRefusal | ApiError,
    "doc_archive": DocArchived | SkillRefusal | ApiError,
    "graphql": GraphqlResponse,
    "view": ViewShown | ApiError,
    "run": RunStarted | ApiError,
    "ingest": Accepted | ApiError,
}


class Op(NamedTuple):
    """One method of one route: what it does, the model of the request body (a media type for a body no model
    describes), the models of its answer and its query names; `media` is the type of the answer, `headers` the request
    headers the route requires, `required` the query names it requires, `status` the codes the handler answers
    success with, and `extra` the answers beside those, each a status, a media type and what the answer means."""

    summary: str
    body: Any = None
    request: Any = None
    query: tuple[str, ...] = ()
    media: str = "application/json"
    headers: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    status: tuple[str, ...] = ("200",)
    extra: tuple[tuple[str, str, str], ...] = ()


def _read(summary: str, kind: str | None = None, *query: str, media: str = "application/json") -> Op:
    return Op(summary, None if kind is None else BODIES[kind], None, query, media)


def _write(summary: str, kind: str, request: Any = None, *status: str) -> Op:
    return Op(summary, BODIES[kind], request, status=status or ("200",))


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
    ("GET", "/api/ledger/{rest}/events"): Op(
        "Stream a ledger's rows as they land", BODIES["ledger_rows"], media=_STREAM
    ),
    ("GET", "/api/ledger/{rest}"): _read("A page of a ledger", "ledger", "before", "limit"),
    ("GET", "/api/doctor"): _read("The contract report", "doctor"),
    ("GET", "/api/health"): _read("Whether the server is ready", "ready"),
    ("GET", "/api/runs"): _read("The workflow runs", "runs"),
    ("GET", "/api/machines/{name}"): _read("One machine's declared config", "machine"),
    ("POST", "/api/machines"): _write("The machines the board draws", "machines", MachineListRequest),
    ("PUT", "/api/machines"): _write("Add a machine to the store", "machine_create", MachineCreateRequest, "201"),
    ("PUT", "/api/machines/{name}"): _write(
        "Write a machine's next version over the base named, with its policy rows", "machine_put", MachinePutRequest
    ),
    ("DELETE", "/api/machines/{name}"): _write("Retire a machine, keeping every version", "machine_retire"),
    ("GET", "/api/done"): _read("A page of finished tasks", "done", "before", "limit"),
    ("GET", "/api/search"): _read("Search tasks", "search", "before", "finished_within_days", "label", "limit", "q"),
    ("GET", "/api/search/similar"): _read(
        "Tasks like a text", "search", "before", "finished_within_days", "label", "limit", "q"
    ),
    ("GET", "/api/harnesses"): _read("The harnesses and their windows", "harnesses"),
    ("GET", "/api/history"): _read("Lane, machine or task-event history", "history", "hours", "machine", "task"),
    ("GET", "/api/history-window"): _read("How many hours of history the store keeps", "window"),
    ("PUT", "/api/history-window"): _write("Set the history window", "window", WindowRequest),
    ("DELETE", "/api/history-window"): _write("Reset the history window to its default", "window"),
    ("GET", "/api/task/{id}"): _read("One task", "task"),
    ("GET", "/api/task-records"): _read("Task records, the ids named when given", "task_records", "ids"),
    ("GET", "/api/retired"): _read("Retired tasks", "retired", "before", "fields", "limit", "milestone", "task"),
    ("POST", "/api/move"): _write("Move tasks to a state", "move", MoveRequest),
    ("POST", "/api/start"): _write("Start a session on a task", "start", StartRequest),
    ("POST", "/api/edit"): _write("Edit a task", "edit", EditRequest),
    ("POST", "/api/archive"): _write("Archive tasks", "archive", ArchiveRequest),
    ("POST", "/api/verdict"): _write("Record a verdict", "verdict", VerdictRequest),
    ("POST", "/api/miss"): _write("Record a miss", "verdict", MissRequest),
    ("POST", "/api/restore"): _write("Restore an archived task", "restore", RestoreRequest),
    ("POST", "/api/take-over"): _write("Take a session over", "take_over", TakeOverRequest),
    ("POST", "/api/retire"): _write("Retire a task", "retire", RetireRequest),
    ("POST", "/api/retired/import"): _write("Import retired tasks", "retired_import", RetiredImportRequest),
    ("POST", "/api/dispatch"): _write("Dispatch a session to a task", "dispatch", DispatchRequest, "202"),
    ("POST", "/api/park"): _write("Park a task", "park", ParkRequest),
    ("POST", "/api/review"): _write("Record a review", "review", ReviewRequest),
    ("POST", "/api/complete"): _write("Complete a task", "complete", CompleteRequest),
    ("POST", "/api/reopen"): _write("Reopen a task", "reopen", ReopenRequest),
    ("POST", "/api/tasks"): _write("Create tasks", "create", CreateRequest, "201", "200"),
    ("PUT", "/api/tasks"): _write("Create tasks", "create", CreateRequest, "201", "200"),
    ("PUT", "/api/tasks/{id}"): _write(
        "Write a task over the base named, or reopen, restore or take it over", "task_put", TaskPutRequest
    ),
    ("DELETE", "/api/tasks/{id}"): _write("Archive a task, recording the `reason` its optional body names", "task_delete"),
    ("GET", "/api/milestones/{id}"): _read("One milestone, archived or open", "milestone"),
    ("PUT", "/api/milestones/{id}"): _write(
        "Write a milestone over the revision named", "milestone_put", MilestonePutRequest
    ),
    ("DELETE", "/api/milestones/{id}"): _write("Archive a milestone", "milestone_archive"),
    ("POST", "/api/milestones"): _write("The open milestones", "milestones", MilestoneListRequest),
    ("PUT", "/api/milestones"): _write("Create a milestone", "milestone_create", MilestoneCreateRequest, "201"),
    ("GET", "/api/docs/{id}"): _read("One doc, archived or open", "doc"),
    ("PUT", "/api/docs/{id}"): _write("Write or restore a doc over the revision named", "doc_put", DocPutRequest),
    ("DELETE", "/api/docs/{id}"): _write("Archive a doc", "doc_archive"),
    ("POST", "/api/docs"): _write("The docs named, without bodies", "docs", DocListRequest),
    ("PUT", "/api/docs"): _write("Create a doc", "doc_create", DocCreateRequest, "201"),
    ("POST", "/api/run/{name}"): _write("Run a workflow", "run"),
    ("POST", "/api/runs/{instance}/{workflow}/rerun"): _write("Rerun a workflow run", "run"),
    ("GET", "/api/admin"): _read("Admin's settings: the scheduler's state, the display and the theme", "admin"),
    ("PUT", "/api/admin"): _write("Change any of Admin's settings, naming only those", "admin", AdminRequest),
    ("GET", "/api/pulls"): _read(
        "Pull requests", "pulls", "bodies", "body_contains", "number", "repo", "state", "task"
    ),
    ("GET", "/api/views/{id}"): _read("The GraphQL document a view stores", "view"),
    ("GET", "/api/openapi"): Op("This document"),
    ("POST", "/graphql"): Op(
        "Run a GraphQL query over the tasks, or follow their changes with a subscription",
        BODIES["graphql"],
        GraphqlRequest,
        extra=(
            ("200", _STREAM, "A `taskChanges` subscription: one `next` event, holding a GraphQL result, for each task change after `from`"),
            ("410", "application/json", "The `from` position is no longer held: the error code is `REREAD`, and the client reads the task list again"),
        ),
    ),
    ("GET", "/metrics"): _read("Prometheus metrics", media="text/plain"),
    ("POST", "/intake/grafana"): _write("Ingest a Grafana alert", "ingest", "application/json"),
    ("POST", "/intake/temporal-completion"): Op(
        "Ingest a Temporal completion",
        BODIES["ingest"],
        query=("workflow",),
        headers=("Nexus-Operation-State", "Nexus-Link"),
        required=("workflow",),
    ),
    ("GET", "/swagger"): Op("The Swagger page of this document", media="text/html"),
}
