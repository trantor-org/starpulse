"""Tasks: a task's record and every write that changes one, and the retired tasks.

- `GET /api/task/{id}`: a task's record, with the pull requests it cites; a read that takes long is logged.
- `GET /api/retired`: the retired tasks, filtered by `task` and `milestone`.
- `POST /api/move`, `start`, `edit`, `archive`, `verdict`, `rating`, `miss`, `restore`, `take-over`, `retire`,
  `retired/import`, `claim`, `park`, `review`, `complete` and `tasks`: a task's writes, each over the seams it needs.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import Response

from starpulse.contracts.api.dto.requests import StartRequest
from starpulse.views.adapters.inbound.api.answering import answer, on_loop, on_worker, query, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, Arrival, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.slow_reads import SlowReads
from starpulse.views.adapters.inbound.api.writing import TaskWrite, guarded, no_writer, whole_body
from starpulse.views.application.commands.lifecycle import park_task, review_task
from starpulse.views.application.commands.moves import claim_task, move_task, start_requested, start_task
from starpulse.views.application.commands.tasks import (
    archive_task,
    complete_task,
    create_task,
    edit_task,
    import_retired,
    record_miss,
    record_rating,
    record_verdict,
    restore_task,
    retire_task,
    retired_list,
    take_over_task,
    task_record,
)
from starpulse.views.application.queries.responses import cited_pulls, resident_pulls
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


def _answer_task(request: Request, status: int, body: dict[str, Any], cited: list[dict[str, Any]]) -> Response:
    if status == 200 and cited:
        body["record"]["pulls"] = cited
    return answer(request, encode("task", body), status)


def _resident_task(request: Request) -> Response | None:
    """The task's answer when memory holds all of it, with no query; None when it needs a worker."""
    api = seams(request)
    name = request.path_params["id"]
    if api.board.read is None or not api.feed.is_resident(name) or (record := api.board.read(name)) is None:
        return None
    if (cited := resident_pulls(api.services.pulls, record.get("references", []))) is None:
        return None
    return _answer_task(request, 200, {"task": name, "record": record}, cited)


def _stored_task(request: Request) -> Response:
    api = seams(request)
    status, body = task_record(api.feed, api.board.read, request.path_params["id"])
    cited = cited_pulls(api.services.pulls, body["record"].get("references", [])) if status == 200 else []
    return _answer_task(request, status, body, cited)


async def task(request: Request) -> Response:
    """A task the feed holds in memory, citing only pull requests memory holds, is answered on the event loop."""
    return on_loop(request, lambda: _resident_task(request)) or await on_worker(request, lambda: _stored_task(request))


@reading
def retired(request: Request) -> Response:
    asked = query(request)
    status, body = retired_list(seams(request).board, asked.get("task", [""])[0], asked.get("milestone", [""])[0])
    return answer(request, encode("retired", body), status)


def routes(api: Api) -> list[ApiRoute]:
    feed, board, services = api.feed, api.board, api.services
    writer = board.writer or no_writer
    assign = board.assign or no_writer
    read, edit, archive, create = board.read, board.edit, board.archive, board.create
    restore, complete = board.restore, board.complete

    def start(request: StartRequest) -> tuple[int, dict[str, Any]]:
        return start_requested(request, feed, assign, services.start_session, services.harnesses)

    slow = SlowReads("/api/task", services.slow_read_s)

    def timed(request: Request, arrival: Arrival) -> AbstractContextManager[Any]:
        return slow.watch(request.path_params["id"], arrival)

    # Every write route, by path: the handler over the seams it needs and the kind of body it answers
    # (`contracts.api.registry.BODIES`). Each handler parses its body through the request model it is declared with.
    writes: dict[str, tuple[TaskWrite, str]] = {
        "/move": (lambda client, raw: move_task(client, raw, feed, writer, start), "move"),
        "/start": (
            lambda client, raw: start_task(client, raw, feed, assign, services.start_session, services.harnesses),
            "start",
        ),
        "/edit": (lambda client, raw: edit_task(client, raw, feed, read, edit), "edit"),
        "/archive": (lambda client, raw: archive_task(client, raw, feed, archive), "archive"),
        "/verdict": (lambda client, raw: record_verdict(client, raw, feed, read, edit), "verdict"),
        "/rating": (lambda client, raw: record_rating(client, raw, feed), "rating"),
        "/miss": (lambda client, raw: record_miss(client, raw, feed, read, edit, archive, create), "verdict"),
        "/restore": (lambda client, raw: restore_task(client, raw, feed, restore), "restore"),
        "/take-over": (lambda client, raw: take_over_task(client, raw, services.take_over, feed), "take_over"),
        "/retire": (lambda client, raw: retire_task(client, raw, board), "retire"),
        "/retired/import": (lambda client, raw: import_retired(client, raw, board), "retired_import"),
        "/claim": (lambda client, raw: claim_task(client, raw, feed, writer), "claim"),
        "/park": (lambda client, raw: park_task(client, raw, feed, read, edit), "park"),
        "/review": (lambda client, raw: review_task(client, raw, feed, read, edit), "review"),
        "/complete": (lambda client, raw: complete_task(client, raw, feed, complete), "complete"),
        "/tasks": (lambda client, raw: create_task(client, raw, create, feed), "create"),
    }
    return [
        ReadRoute("/task/{id:path}", task, timed),
        ReadRoute("/retired", retired),
        *(WriteRoute(path, ("POST",), guarded(kind, whole_body(handler))) for path, (handler, kind) in writes.items()),
    ]
