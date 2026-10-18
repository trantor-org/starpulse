"""The routes the server answers: their paths, which are writes and the body each answers."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:  # annotation only: a runtime import would put the autopilot in the Delivery worker's import closure
    pass


#: The page's one address and the retired per-graph ones, which the page redirects to their level.
_PAGES = {"/", "/board", "/runs"}


_RUN = "/api/run/"


_RERUN = "/api/runs/"


_RERUN_TAIL = "/rerun"


_MOVE = "/api/move"


_START = "/api/start"


_WINDOW = "/api/history-window"


_FORWARDING = "/api/forwarding"


_AUTOPILOT = "/api/autopilot"


_TASK = "/api/task/"


_LEDGER = "/api/ledger/"


_SNAPSHOT_BODY = "/api/events/body/"


_HELD = "/api/held"


_LANES = "/api/lanes"


_EDIT = "/api/edit"


_ARCHIVE = "/api/archive"
_VERDICT = "/api/verdict"
_MISS = "/api/miss"


_RESTORE = "/api/restore"


_RETIRE = "/api/retire"


_RETIRED = "/api/retired"


_RETIRED_IMPORT = "/api/retired/import"


_COMPLETE = "/api/complete"


_CLAIM = "/api/claim"


_PARK = "/api/park"


_REVIEW = "/api/review"


_TASKS = "/api/tasks"


_MILESTONES = "/api/milestones"


_MILESTONE_EDIT = "/api/milestones/edit"


_MILESTONE_ARCHIVE = "/api/milestones/archive"


_DOCS = "/api/docs"


_DOC_EDIT = "/api/docs/edit"


_DOC_ARCHIVE = "/api/docs/archive"


_DOC_RESTORE = "/api/docs/restore"


_INGEST = "/api/runs/events"


_FORWARD = "/api/forward"


_INSIGHTS = "/api/insights"


_PULL_REFRESH = "/api/pulls/refresh"


#: The write routes of milestone records; `/api/milestones/<id>` reads one, so a GET of these answers 405.
_MILESTONE_WRITES = frozenset({_MILESTONES, _MILESTONE_EDIT, _MILESTONE_ARCHIVE})


#: The write routes of doc records; `/api/docs/<id>` reads one, so a GET of these answers 405.
_DOC_WRITES = frozenset({_DOCS, _DOC_EDIT, _DOC_ARCHIVE, _DOC_RESTORE})


#: The write routes of retired tasks; `/api/retired` reads them.
_RETIRED_WRITES = frozenset({_RETIRE, _RETIRED_IMPORT})


#: The write routes whose JSON body a handler in `writes` reads whole.
_TASK_WRITES = frozenset(
    {
        _MOVE,
        _START,
        _EDIT,
        _ARCHIVE,
        _VERDICT,
        _MISS,
        _RESTORE,
        _COMPLETE,
        _CLAIM,
        _PARK,
        _REVIEW,
        _TASKS,
        *_MILESTONE_WRITES,
        *_DOC_WRITES,
        *_RETIRED_WRITES,
    }
)


#: The body each write route answers, by `contracts.api.registry.BODIES`; a run and a rerun answer `run`.
_WRITES = {
    _MOVE: "move",
    _START: "start",
    _EDIT: "edit",
    _ARCHIVE: "archive",
    _VERDICT: "verdict",
    _MISS: "verdict",
    _RESTORE: "restore",
    _RETIRE: "retire",
    _RETIRED_IMPORT: "retired_import",
    _COMPLETE: "complete",
    _CLAIM: "claim",
    _PARK: "park",
    _REVIEW: "review",
    _TASKS: "create",
    _MILESTONES: "milestone_create",
    _MILESTONE_EDIT: "milestone_edit",
    _MILESTONE_ARCHIVE: "milestone_archive",
    _DOCS: "doc_create",
    _DOC_EDIT: "doc_edit",
    _DOC_ARCHIVE: "doc_archive",
    _DOC_RESTORE: "doc_restore",
    _INGEST: "ingest",
    _FORWARD: "forward",
    _INSIGHTS: "insight",
    _PULL_REFRESH: "ingest",
}


def _is_rerun(path: str) -> bool:
    """Whether `path` is `/api/runs/<instance>/<workflow>/rerun`; the ingest route `/api/runs/events` is not."""
    return path.startswith(_RERUN) and path.endswith(_RERUN_TAIL) and path.count("/") == 5
