"""The write routes as request-in, response-out handlers: no socket and no web framework, so the ASGI app (and any
other front) calls the same ones."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol
from urllib.parse import unquote

from starpulse.board.model.seam import OPERATOR, Written
from starpulse.contracts.api.dto.requests import StartRequest
from starpulse.pulls.adapters.inbound.pull_refresh import MAX_BODY as MAX_REFRESH_BODY
from starpulse.runs.ingest import MAX_BATCH_BODY
from starpulse.views.encoding import encode
from starpulse.views.reads import Response
from starpulse.views.routes import (
    _ARCHIVE,
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
    _RATING,
    _RERUN,
    _RERUN_TAIL,
    _RESTORE,
    _RETIRE,
    _RETIRED_IMPORT,
    _REVIEW,
    _RUN,
    _SCHEDULER,
    _START,
    _TAKE_OVER,
    _TASKS,
    _VERDICT,
    _WINDOW,
)
from starpulse.views.writes import (
    RETRY_AFTER_S,
    archive_doc,
    archive_milestone,
    archive_task,
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
    review_task,
    run_dag,
    scheduler,
    start_requested,
    start_task,
    take_over_task,
    write_refusal,
)

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.board.adapters.history_window import HistoryWindow
    from starpulse.board.board_feed import BoardFeed
    from starpulse.board.model.seam import Board
    from starpulse.views.services import Services


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
WriteHandler = Callable[[WriteRequest], "Response | None"]
WriteRoute = tuple[str, tuple[str, ...], WriteHandler]


def _answered(kind: str, body: dict, status: int) -> Response:
    """The write's answer; a 503 asks the client to send it again after `RETRY_AFTER_S`."""
    return Response(encode(kind, body), status, retry_after=RETRY_AFTER_S if status == 503 else None)


class WriteRoutes:
    """Every route that changes something: the board's writes, a workflow's run, the token-guarded pushes and the
    settings a page puts."""

    def __init__(self, feed: BoardFeed, window: HistoryWindow, board: Board, services: Services) -> None:
        writer = board.writer or _no_writer
        assign = board.assign or _no_writer
        read, edit, archive, create = board.read, board.edit, board.archive, board.create
        restore, complete, milestones = board.restore, board.complete, board

        def start(request: StartRequest) -> tuple[int, dict[str, Any]]:
            return start_requested(request, feed, assign, services.start_session, services.harnesses)

        self._feed = feed
        self._window = window
        self._starts = services.starts
        self._reruns = services.reruns or {}
        self._run_safe = services.run_safe
        self._scheduler = services.scheduler
        # Every write route, by path: the handler over the seams it needs and the kind of body it answers
        # (`contracts.api.registry.BODIES`). Each handler parses its body through the request model it is declared with.
        self._writes: dict[str, tuple[TaskWrite, str]] = {
            _MOVE: (lambda client, raw: move_task(client, raw, feed, writer, start), "move"),
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
            _TAKE_OVER: (lambda client, raw: take_over_task(client, raw, services.take_over, feed), "take_over"),
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
        # The pushes a deployment may leave unconfigured: a POST of one answers 404.
        self._pull_refresh = services.pull_refresh
        self._events = services.events

    def routes(self) -> list[WriteRoute]:
        """Every write route as its path template (`ReadRoutes.routes` says how it is written), the methods it answers
        and its handler. A handler answers None where a deployment leaves its route unconfigured."""
        guarded = [
            (path, ("POST",), self._guarded(kind, self._body(handler)))
            for path, (handler, kind) in self._writes.items()
        ]
        return [
            *guarded,
            (f"{_RUN}{{name:path}}", ("POST",), self._guarded("run", self._run)),
            (f"{_RERUN}{{instance}}/{{workflow}}{_RERUN_TAIL}", ("POST",), self._guarded("run", self._rerun)),
            (_PULL_REFRESH, ("POST",), self._push),
            (_MACHINE_EVENTS, ("POST",), self._machine_events),
            (_SCHEDULER, ("PUT",), self._guarded("scheduler", self._scheduled)),
            (_WINDOW, ("PUT", "DELETE"), self._guarded("window", self._windowed)),
        ]

    def _guarded(self, kind: str, answer: Callable[[WriteRequest], tuple[int, dict]]) -> WriteHandler:
        """`answer` as a `kind` body, unless another web page may have sent the request."""

        def handle(request: WriteRequest) -> Response:
            refusal = self._refused(request)
            if refusal is not None:
                return refusal
            status, body = answer(request)
            return _answered(kind, body, status)

        return handle

    def _body(self, handler: TaskWrite) -> Callable[[WriteRequest], tuple[int, dict]]:
        return lambda request: handler(request.client, self._whole(request))

    def _run(self, request: WriteRequest) -> tuple[int, dict]:
        name = unquote(request.path.removeprefix(_RUN))
        return run_dag(request.client, name, self._starts, self._run_safe)

    def _rerun(self, request: WriteRequest) -> tuple[int, dict]:
        name = unquote(request.path.removeprefix(_RERUN).removesuffix(_RERUN_TAIL))
        return rerun_dag(request.client, name, self._feed, self._reruns, self._run_safe)

    def _scheduled(self, request: WriteRequest) -> tuple[int, dict]:
        return scheduler(request.client, "PUT", self._whole(request), self._scheduler)

    def _windowed(self, request: WriteRequest) -> tuple[int, dict]:
        return history_window(request.client, request.method, self._whole(request), self._window)

    def _push(self, request: WriteRequest) -> Response | None:
        push = self._pull_refresh
        return None if push is None else self._pushed(request, "ingest", push, MAX_REFRESH_BODY)

    def _machine_events(self, request: WriteRequest) -> Response | None:
        events = self._events
        if events is None:
            return None
        content_type = request.headers.get("Content-Type")
        return self._pushed(request, "ingest", lambda auth, raw: events(auth, content_type, raw), MAX_BATCH_BODY)

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
        return _answered(kind, body, status)
