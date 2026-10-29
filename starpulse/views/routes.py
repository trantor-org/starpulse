"""The paths the routes answer."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass


#: The page's one address and the retired per-graph ones, which the page redirects to their level.
_PAGES = {"/", "/board", "/runs"}


_RUN = "/api/run/"


_RERUN = "/api/runs/"


_RERUN_TAIL = "/rerun"


_MOVE = "/api/move"


_START = "/api/start"


_WINDOW = "/api/history-window"


_SCHEDULER = "/api/scheduler"


_TASK = "/api/task/"


_LEDGER = "/api/ledger/"


_SNAPSHOT_BODY = "/api/events/body/"


_HELD = "/api/held"


_LANES = "/api/lanes"


_EDIT = "/api/edit"


_ARCHIVE = "/api/archive"
_VERDICT = "/api/verdict"
_RATING = "/api/rating"
_MISS = "/api/miss"


_RESTORE = "/api/restore"


_RETIRE = "/api/retire"


_TAKE_OVER = "/api/take-over"


_RETIRED = "/api/retired"


_RETIRED_IMPORT = "/api/retired/import"


_COMPLETE = "/api/complete"


_CLAIM = "/api/claim"


_PARK = "/api/park"


_ANSWER = "/api/answer"


_REVIEW = "/api/review"


_TASKS = "/api/tasks"


_MILESTONES = "/api/milestones"


_MILESTONE_EDIT = "/api/milestones/edit"


_MILESTONE_ARCHIVE = "/api/milestones/archive"


_DOCS = "/api/docs"


_DOC_EDIT = "/api/docs/edit"


_DOC_ARCHIVE = "/api/docs/archive"


_DOC_RESTORE = "/api/docs/restore"


_MACHINE_EVENTS = "/api/machine-events"


_PULL_REFRESH = "/api/pulls/refresh"
