"""The route tables: the model of each event, response, request and body the API names."""

from typing import Any, NamedTuple

from pydantic import BaseModel

from starpulse.contracts.api.dto.admin import AdminState
from starpulse.contracts.api.dto.dag import DagBody, Jobs
from starpulse.contracts.api.dto.errors import (
    ApiError,
    DeliveredElsewhere,
    NotHolder,
    SkillRefusal,
    StaleEdit,
    UnrecognisedUrl,
    WindowTooLong,
)
from starpulse.contracts.api.dto.graphql import GraphqlRequest, GraphqlResponse, ViewShown
from starpulse.contracts.api.dto.harnesses import Harnesses, WindowState
from starpulse.contracts.api.dto.milestones import (
    Docs,
    DocShown,
    Milestones,
    MilestoneShown,
    RetiredTasks,
    TaskRecord,
    TaskRecords,
)
from starpulse.contracts.api.dto.links import Link
from starpulse.contracts.api.dto.pages import DailyReports, DonePage, MachineDetail, Machines
from starpulse.contracts.api.dto.report import ContractReport, ReadyReport
from starpulse.contracts.api.dto.requests import (
    AdminRequest,
    HarnessesRequest,
    CreateRequest,
    DocCreateRequest,
    DailyReportListRequest,
    DocListRequest,
    DocPutRequest,
    JobListRequest,
    LinkDeleteRequest,
    LinkPutRequest,
    MachineCreateRequest,
    MachineListRequest,
    MachinePutRequest,
    MilestoneCreateRequest,
    MilestoneListRequest,
    MilestonePutRequest,
    StartRequest,
    StepsRequest,
    TaskPutRequest,
    WindowRequest,
)
from starpulse.contracts.api.dto.results import (
    Accepted,
    Archived,
    Completed,
    Created,
    CreatedEach,
    DuplicatesChecked,
    Dispatched,
    DocArchived,
    DocCreated,
    DocEdited,
    Edited,
    MachineRetired,
    MachineWritten,
    MilestoneArchived,
    MilestoneCreated,
    MilestoneEdited,
    FreezeRequested,
    Parked,
    Reopened,
    Restored,
    Retired,
    Started,
    TakenOver,
)
from starpulse.contracts.api.dto.search import SearchResults
from starpulse.contracts.api.dto.snapshot import Snapshot
from starpulse.contracts.api.dto.trajectories import Trajectories
from starpulse.contracts.api.dto.transitions import (
    Spend,
)

#: Each GET route's `200` body, by path; `/api/task/<id>` by its prefix.
RESPONSES: dict[str, Any] = {
    "/api/snapshot": Snapshot,
    "/api/machines/": MachineDetail,
    "/api/harnesses": Harnesses,
    "/api/history-window": WindowState,
    "/api/doctor": ContractReport,
    "/api/health": ReadyReport,
    "/api/flows": Snapshot,
    "/api/jobs/": DagBody,
    "/api/task/": TaskRecord,
    "/api/task-records": TaskRecords,
    "/api/milestones/": MilestoneShown,
    "/api/docs/": DocShown,
    "/api/retired": RetiredTasks,
    "/api/search": SearchResults,
    "/api/search/similar": SearchResults,
    "/api/views/": ViewShown,
    "/api/admin": AdminState,
}

#: Each write route's request body.
REQUESTS: dict[str, type[BaseModel]] = {
    "/api/start": StartRequest,
    "/api/steps": StepsRequest,
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
    "/api/harnesses": HarnessesRequest,
}

#: Each list route's request body: a POST to a path a PUT also writes, which `REQUESTS` names.
LISTS: dict[str, type[BaseModel]] = {
    "/api/jobs": JobListRequest,
    "/api/machines": MachineListRequest,
    "/api/milestones": MilestoneListRequest,
    "/api/docs": DocListRequest,
    "/api/daily-reports": DailyReportListRequest,
}

def writes(method: str, path: str) -> bool:
    """Whether a route writes: any method but GET, bar the POSTs that only list."""
    return method != "GET" and not (method == "POST" and path in LISTS)


#: Every body a route may send, by route: what `encode` validates a body against.
BODIES: dict[str, Any] = {
    "error": ApiError,
    "snapshot": Snapshot,
    "machines": Machines | ApiError,
    "daily_reports": DailyReports | ApiError,
    "machine": MachineDetail | ApiError,
    "machine_create": MachineWritten | ApiError,
    "machine_put": MachineWritten | ApiError,
    "machine_retire": MachineRetired | ApiError,
    "done": DonePage | ApiError,
    "search": SearchResults | ApiError,
    "spend": Spend | ApiError | WindowTooLong,
    "trajectories": Trajectories | ApiError | WindowTooLong,
    "harnesses": Harnesses | ApiError,
    "window": WindowState | ApiError,
    "admin": AdminState | ApiError,
    "doctor": ContractReport,
    "ready": ReadyReport,
    "jobs": Jobs | ApiError,
    "job": DagBody | ApiError,
    "task": TaskRecord | ApiError,
    "task_records": TaskRecords,
    "start": Started | SkillRefusal | ApiError,
    "retired": RetiredTasks | ApiError,
    "create": Created | CreatedEach | DuplicatesChecked | SkillRefusal | ApiError,
    "task_link_put": Link | NotHolder | DeliveredElsewhere | UnrecognisedUrl | ApiError,
    "task_link_delete": Link | NotHolder | ApiError,
    "task_put": Edited
    | StaleEdit
    | Restored
    | Retired
    | Reopened
    | Completed
    | TakenOver
    | Parked
    | FreezeRequested
    | Dispatched
    | SkillRefusal
    | ApiError,
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
    "graphql": GraphqlResponse | ApiError,
    "view": ViewShown | ApiError,
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

#: Every route the app serves outside the page's own files, by method and path: the model of each body it takes and
#: answers with. `tests/unit/contracts/test_openapi.py` fails when the app mounts a route this table lacks.
ROUTES: dict[tuple[str, str], Op] = {
    ("GET", "/api/snapshot"): _read("The board snapshot", "snapshot", "view"),
    ("GET", "/api/flows"): Op("The flows of the board", Snapshot),
    ("GET", "/api/doctor"): _read("The contract report", "doctor"),
    ("GET", "/api/health"): _read("Whether the server is ready", "ready"),
    ("GET", "/api/jobs/{name}"): _read("One job, with its runner's start page", "job"),
    ("GET", "/api/machines/{name}"): _read("One machine's declared config", "machine"),
    ("POST", "/api/machines"): _write("The machines the board draws", "machines", MachineListRequest),
    ("PUT", "/api/machines"): _write("Add a machine to the store", "machine_create", MachineCreateRequest, "201"),
    ("PUT", "/api/machines/{name}"): _write(
        "Write a machine's next version over the base named, with its policy rows", "machine_put", MachinePutRequest
    ),
    ("DELETE", "/api/machines/{name}"): _write("Retire a machine, keeping every version", "machine_retire"),
    ("GET", "/api/done"): _read("A page of finished tasks", "done", "before", "limit", "milestone"),
    ("GET", "/api/search"): _read("Search tasks", "search", "before", "finished_within_days", "label", "limit", "q"),
    ("GET", "/api/search/similar"): _read(
        "Tasks like a text", "search", "before", "finished_within_days", "label", "limit", "q"
    ),
    ("GET", "/api/harnesses"): _read("The harnesses and their windows", "harnesses"),
    ("PUT", "/api/harnesses"): _write("Change the tiers and any harness, naming only the harnesses that change", "harnesses", HarnessesRequest),
    ("GET", "/api/history-window"): _read("How many hours of history the store keeps", "window"),
    ("PUT", "/api/history-window"): _write("Set the history window", "window", WindowRequest),
    ("DELETE", "/api/history-window"): _write("Reset the history window to its default", "window"),
    ("GET", "/api/task/{id}"): _read("One task, by its key, an alias it carries or its UUID", "task"),
    ("GET", "/api/task-records"): _read("Task records, the ids named when given", "task_records", "ids"),
    ("GET", "/api/retired"): _read("Retired tasks", "retired", "before", "fields", "limit", "milestone", "task"),
    ("POST", "/api/start"): _write("Start a session on a task", "start", StartRequest),
    ("POST", "/api/steps"): _write("Record the seconds each step of an agent command took", "ingest", StepsRequest),
    ("PUT", "/api/tasks"): _write("Create tasks", "create", CreateRequest, "201", "200"),
    ("PUT", "/api/tasks/{id}"): _write(
        "Write a task over the base named, or reopen, complete, restore, retire, take over, park, ask for a freeze or"
        " unfreeze or dispatch a session to it",
        "task_put",
        TaskPutRequest,
        "200",
        "202",
    ),
    ("PUT", "/api/tasks/{id}/links"): _write(
        "Ask the task actor to link the task to a pull request, which only the session holding the task may",
        "task_link_put",
        LinkPutRequest,
        "200",
        "201",
    ),
    ("DELETE", "/api/tasks/{id}/links"): _write(
        "Ask the task actor to remove one of the task's links, which only the session holding the task may",
        "task_link_delete",
        LinkDeleteRequest,
    ),
    ("DELETE", "/api/tasks/{id}"): _write(
        "Archive a task, recording the `reason` its optional body names", "task_delete"
    ),
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
    ("POST", "/api/daily-reports"): _write(
        "One machine's daily report of counts and durations", "daily_reports", DailyReportListRequest
    ),
    ("POST", "/api/docs"): _write("The docs named, without bodies", "docs", DocListRequest),
    ("PUT", "/api/docs"): _write("Create a doc", "doc_create", DocCreateRequest, "201"),
    ("POST", "/api/jobs"): _write("The jobs, at a stream position", "jobs", JobListRequest),
    ("GET", "/api/admin"): _read("Admin's settings: the scheduler's state, the display and the theme", "admin"),
    ("PUT", "/api/admin"): _write("Change any of Admin's settings, naming only those", "admin", AdminRequest),
    ("GET", "/api/views/{id}"): _read("The GraphQL document a view stores", "view"),
    ("GET", "/api/openapi"): Op("This document"),
    ("POST", "/graphql"): Op(
        "Run a GraphQL query over the tasks (open, settled, per-milestone done counts and every machine's, each with its phase, substate, skill, criteria, pause reason, readable verdict, release and interactive mark), the board (columns, state roles, machines, dags) and a ledger's occurrences, or follow their changes with a subscription",
        BODIES["graphql"],
        GraphqlRequest,
        extra=(
            (
                "200",
                _STREAM,
                "A `taskChanges` subscription: one `next` event, holding a GraphQL result, for each task change after `from`, a move on a machine other than the board included; an `occurrenceChanges` subscription: the ledger's newest page first (`head`), then one for each change to its rows, the merge ledger's strip and pins included",
            ),
            ("404", "application/json", "An `occurrenceChanges` subscription for an event no workflow is tied to"),
            (
                "410",
                "application/json",
                "The `from` position is no longer held: the error code is `REREAD`, and the client reads the task list again",
            ),
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
