"""The write routes as request-in, response-out handlers: no socket and no web framework, so the ASGI app (and any
other front) calls the same ones."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple, Protocol
from urllib.parse import unquote

from starpulse._internal.board.seam import OPERATOR, Written
from starpulse._internal.pulls.pull_refresh import MAX_BODY as MAX_REFRESH_BODY
from starpulse._internal.runs.ingest import MAX_BATCH_BODY
from starpulse._internal.server.encoding import encode
from starpulse._internal.server.reads import Response
from starpulse._internal.server.routes import (
    _ARCHIVE,
    _SCHEDULER,
    _CLAIM,
    _COMPLETE,
    _DOC_ARCHIVE,
    _DOC_EDIT,
    _DOC_RESTORE,
    _DOCS,
    _EDIT,
    _MACHINE_EVENTS,
    _MILESTONE_ARCHIVE,
    _MILESTONE_EDIT,
    _MILESTONES,
    _MISS,
    _MOVE,
    _PARK,
    _PULL_REFRESH,
    _TAKE_OVER,
    _RERUN,
    _RERUN_TAIL,
    _RESTORE,
    _RETIRE,
    _RETIRED_IMPORT,
    _REVIEW,
    _RATING,
    _RUN,
    _START,
    _TASKS,
    _VERDICT,
    _WINDOW,
    _is_rerun,
)
from starpulse._internal.server.writes import (
    archive_doc,
    archive_milestone,
    archive_task,
    scheduler,
    claim_task,
    complete_task,
    create_doc,
    create_milestone,
    create_task,
    edit_doc,
    edit_milestone,
    edit_task,
    history_window,
    import_retired,
    move_task,
    park_task,
    record_miss,
    record_rating,
    record_verdict,
    rerun_dag,
    restore_doc,
    restore_task,
    retire_task,
    take_over_task,
    review_task,
    run_dag,
    start_task,
    write_refusal,
)

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse._internal.board.seam import Board
    from starpulse._internal.feed.board_feed import BoardFeed
    from starpulse._internal.feed.history_window import HistoryWindow
    from starpulse._internal.server.services import Services


class Headers(Protocol):
    """The request headers a write reads: a lookup by name that ignores case."""

    def get(self, name: str) -> str | None: ...


class WriteRequest(NamedTuple):
    """A POST, PUT or DELETE as a server hands it over: the method, the path, the client's address, the headers and
    `body`, which reads the given number of bytes of the request body (a server reads it only once a route wants it)."""

    method: str
    path: str
    client: str
    headers: Headers
    body: Callable[[int], bytes]


def _no_writer(task: str, status: str, actor: str = OPERATOR) -> Written:
    return Written(False, "no board writer is configured", unavailable=True)


TaskWrite = Callable[[str, bytes], tuple[int, dict]]
Pushed = Callable[[str | None, bytes], tuple[int, dict]]


class WriteRoutes:
    """Every route that changes something: the board's writes, a workflow's run, the token-guarded pushes and the
    settings a page puts. A call answers a `WriteRequest` with its `Response`, or None where the method and path are
    no write route."""

    def __init__(self, feed: BoardFeed, window: HistoryWindow, board: Board, services: Services) -> None:
        writer = board.writer or _no_writer
        assign = board.assign or _no_writer
        read, edit, archive, create = board.read, board.edit, board.archive, board.create
        restore, complete, milestones = board.restore, board.complete, board
        self._feed = feed
        self._window = window
        self._starts = services.starts
        self._reruns = services.reruns or {}
        self._run_safe = services.run_safe
        self._scheduler = services.scheduler
        # Every write route, by path: the handler over the seams it needs and the kind of body it answers
        # (`contracts.api.registry.BODIES`). Each handler parses its body through the request model it is declared with.
        self._writes: dict[str, tuple[TaskWrite, str]] = {
            _MOVE: (lambda client, raw: move_task(client, raw, feed, writer), "move"),
            _START: (
                lambda client, raw: start_task(client, raw, feed, assign, services.start_session, services.harnesses),
                "start",
            ),
            _EDIT: (lambda client, raw: edit_task(client, raw, feed, read, edit), "edit"),
            _ARCHIVE: (lambda client, raw: archive_task(client, raw, feed, archive), "archive"),
            _VERDICT: (lambda client, raw: record_verdict(client, raw, feed, read, edit), "verdict"),
            _RATING: (lambda client, raw: record_rating(client, raw, feed), "rating"),
            _MISS: (lambda client, raw: record_miss(client, raw, feed, read, edit, archive, create), "verdict"),
            _RESTORE: (lambda client, raw: restore_task(client, raw, feed, restore), "restore"),
            _TAKE_OVER: (lambda client, raw: take_over_task(client, raw, services.take_over), "take_over"),
            _RETIRE: (lambda client, raw: retire_task(client, raw, milestones), "retire"),
            _RETIRED_IMPORT: (lambda client, raw: import_retired(client, raw, milestones), "retired_import"),
            _CLAIM: (lambda client, raw: claim_task(client, raw, feed, writer), "claim"),
            _PARK: (lambda client, raw: park_task(client, raw, feed, read, edit), "park"),
            _REVIEW: (lambda client, raw: review_task(client, raw, feed, read, edit), "review"),
            _COMPLETE: (lambda client, raw: complete_task(client, raw, feed, complete), "complete"),
            _TASKS: (lambda client, raw: create_task(client, raw, create, feed), "create"),
            _MILESTONES: (lambda client, raw: create_milestone(client, raw, milestones), "milestone_create"),
            _MILESTONE_EDIT: (lambda client, raw: edit_milestone(client, raw, milestones), "milestone_edit"),
            _MILESTONE_ARCHIVE: (lambda client, raw: archive_milestone(client, raw, milestones), "milestone_archive"),
            _DOCS: (lambda client, raw: create_doc(client, raw, milestones), "doc_create"),
            _DOC_EDIT: (lambda client, raw: edit_doc(client, raw, milestones), "doc_edit"),
            _DOC_ARCHIVE: (lambda client, raw: archive_doc(client, raw, milestones), "doc_archive"),
            _DOC_RESTORE: (lambda client, raw: restore_doc(client, raw, milestones), "doc_restore"),
        }
        # The pushes a deployment may leave unconfigured: their route is then none, and a POST of it answers 404.
        self._pushes: dict[str, tuple[Pushed | None, int, str]] = {
            _PULL_REFRESH: (services.pull_refresh, MAX_REFRESH_BODY, "ingest"),
        }
        self._events = services.events

    def post_only(self, path: str) -> bool:
        """Whether `path` is a route a GET is refused: a write (or run) that answers 405, though a read may share its prefix."""
        return path.startswith(_RUN) or _is_rerun(path) or path in {*self._writes, _MACHINE_EVENTS, _PULL_REFRESH}

    def __call__(self, request: WriteRequest) -> Response | None:
        if request.method == "POST":
            return self._post(request)
        if request.method == "PUT":
            return self._put(request)
        if request.method == "DELETE":
            return self._delete(request)
        return None

    def _post(self, request: WriteRequest) -> Response | None:
        path = request.path
        if (path in self._writes or path.startswith(_RUN) or _is_rerun(path)) and (
            refusal := self._refused(request)
        ) is not None:
            return refusal
        kind = "run"
        push, limit, pushed_kind = self._pushes.get(path, (None, 0, ""))
        if path in self._writes:
            handler, kind = self._writes[path]
            status, body = handler(request.client, self._whole(request))
        elif push is not None:
            return self._pushed(request, pushed_kind, push, limit)
        elif path == _MACHINE_EVENTS and self._events is not None:
            content_type = request.headers.get("Content-Type")
            events = self._events
            return self._pushed(request, "ingest", lambda auth, raw: events(auth, content_type, raw), MAX_BATCH_BODY)
        elif _is_rerun(path):
            name = unquote(path.removeprefix(_RERUN).removesuffix(_RERUN_TAIL))
            status, body = rerun_dag(request.client, name, self._feed, self._reruns, self._run_safe)
        elif path.startswith(_RUN):
            status, body = run_dag(request.client, unquote(path.removeprefix(_RUN)), self._starts, self._run_safe)
        else:
            return None
        return Response(encode(kind, body), status)

    def _put(self, request: WriteRequest) -> Response | None:
        """The switches a page puts: the scheduler's and the history window."""
        path = request.path
        if path == _SCHEDULER:
            return self._guarded(
                request, "scheduler", lambda raw: scheduler(request.client, "PUT", raw, self._scheduler)
            )
        return self._windowed(request)

    def _delete(self, request: WriteRequest) -> Response | None:
        return self._windowed(request)

    def _windowed(self, request: WriteRequest) -> Response | None:
        """The history window's PUT or DELETE."""
        if request.path != _WINDOW:
            return None
        return self._guarded(
            request, "window", lambda raw: history_window(request.client, request.method, raw, self._window)
        )

    def _guarded(self, request: WriteRequest, kind: str, answer: Callable[[bytes], tuple[int, dict]]) -> Response:
        """`answer` for the whole body of `request` as a `kind` body, unless another web page may have sent it."""
        refusal = self._refused(request)
        if refusal is not None:
            return refusal
        status, body = answer(self._whole(request))
        return Response(encode(kind, body), status)

    def _refused(self, request: WriteRequest) -> Response | None:
        """The refusal of a write another web page may have sent, or None."""
        headers = request.headers
        refusal = write_refusal(headers.get("Origin"), headers.get("Host"), headers.get("Content-Type"))
        return None if refusal is None else Response(encode("error", refusal[1]), refusal[0])

    def _whole(self, request: WriteRequest) -> bytes:
        return request.body(int(request.headers.get("Content-Length") or 0))

    def _pushed(self, request: WriteRequest, kind: str, ingest: Pushed, limit: int) -> Response:
        """Answer one token-guarded push; a body over `limit` is refused unread and the connection closed, since the
        body it left cannot be skipped."""
        try:
            declared = int(request.headers.get("Content-Length") or 0)
        except ValueError:
            declared = 0
        if declared > limit:
            return Response(encode(kind, {"error": f"a body is at most {limit} bytes"}), 413, close=True)
        status, body = ingest(request.headers.get("Authorization"), request.body(max(declared, 0)))
        return Response(encode(kind, body), status)
