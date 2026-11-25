"""Tasks: a task's record and every write that changes one, and the retired tasks.

- `GET /api/task/{id}`: a task's record, with the pull requests it cites; a read that takes long is logged.
- `GET /api/task-records?ids=A,B`: the records of the tasks named, in one read; a task the board cannot read is left out.
- `GET /api/retired`: one page of the retired tasks, newest first, at most `limit` after the `before` cursor, with
  `next` for the page that follows; or those of a `task` or `milestone`, or as `{task, dependencies}` for
  `fields=dependencies`, unpaged.
- `PUT /api/tasks` creates; `PUT /api/tasks/{id}` writes over the `base` it names, or reopens (`reopen`), completes
  (`completed: true`), restores (`archived: false`), takes over (`interactive: true`), parks (`park`) or dispatches a
  session (`assignee`); `DELETE /api/tasks/{id}` archives: the task writes.
- `POST /api/start`, `verdict` and `retire`: a task's writes by verb, each over the seams it needs.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from starpulse.board.adapters.holder_idle import started as started_by
from starpulse.contracts.api.dto.milestones import RetiredTask
from starpulse.views.adapters.inbound.api.answering import answer, client, on_worker, query, reading, seams
from starpulse.views.adapters.inbound.api.slow_reads import SlowReads
from starpulse.views.adapters.inbound.api.table import ApiRoute, Arrival, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import TaskWrite, guarded, whole, whole_body
from starpulse.views.application.commands.moves import (
    start_task,
)
from starpulse.views.application.commands.tasks import (
    create_task,
    delete_task,
    retire_task,
    retired_list,
    retired_page,
    put_task,
    task_record,
)
from starpulse.views.application.queries.responses import cited_pulls
from starpulse.views.model.encoding import encode, encode_stream

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


def _stored_record(api: Api, name: str) -> tuple[int, dict[str, Any]]:
    """The task `name` as the board stores it, with the pull requests its references cite attached."""
    status, body = task_record(api.feed, api.board.read, name, api.board.read_archived)
    if status == 200 and (cited := cited_pulls(api.services.pulls, body["record"].get("references", []))):
        body["record"]["pulls"] = cited
    return status, body


def _stored_task(request: Request) -> Response:
    status, body = _stored_record(seams(request), request.path_params["id"])
    return answer(request, encode("task", body), status)


async def task(request: Request) -> Response:
    """One task's record, read on a worker."""
    return await on_worker(request, lambda: _stored_task(request))


def _stored_records(request: Request) -> Response:
    api = seams(request)
    records = []
    with api.feed.pinned_rows():
        for name in query(request).get("ids", [""])[0].split(","):
            status, body = _stored_record(api, name)
            if status == 200:
                records.append(body)
    return answer(request, encode("task_records", {"records": records}), 200)


async def task_records(request: Request) -> Response:
    return await on_worker(request, lambda: _stored_records(request))


#: The one thread that reads and encodes every retired task: a free-threaded thread keeps the heap pages of what it
#: built, so a dump built on whichever request thread took it left each of 40 concurrent requests' pages held (9 GB).
_WHOLE_DUMP = ThreadPoolExecutor(1, thread_name_prefix="retired-dump")


async def _on_dump_thread(chunks: Iterator[bytes]) -> AsyncIterator[bytes]:
    """`chunks`, each drawn on `_WHOLE_DUMP`, so the dump's rows are read and encoded a batch at a time, never whole."""
    loop = asyncio.get_running_loop()
    while (chunk := await loop.run_in_executor(_WHOLE_DUMP, next, chunks, None)) is not None:
        yield chunk


@reading
def retired(request: Request) -> Response:
    asked = query(request)
    task, milestone, fields, limit, before = (
        asked.get(name, [""])[0] for name in ("task", "milestone", "fields", "limit", "before")
    )

    board = seams(request).board
    if task or fields:
        status, body = retired_list(board, task, milestone, fields)
        return answer(request, encode("retired", body), status)
    if not milestone:
        status, body = retired_page(board, limit, before)
        return answer(request, encode("retired", body), status)
    status, body = _WHOLE_DUMP.submit(retired_list, board, task, milestone, fields).result()
    if status != 200:
        return answer(request, encode("retired", body), status)
    chunks = encode_stream("retired", {}, "tasks", RetiredTask, body["tasks"])
    return StreamingResponse(
        _on_dump_thread(chunks), media_type="application/json", headers={"cache-control": "no-store"}
    )


def routes(api: Api) -> list[ApiRoute]:
    feed, board, services = api.feed, api.board, api.services
    assign, create = board.assign, board.create

    def cited(task: str) -> list[dict[str, Any]]:
        return _stored_record(api, task)[1].get("record", {}).get("pulls", [])

    def landed(task: str) -> bool:
        return any(pull.get("merged") or pull.get("state") == "MERGED" for pull in cited(task))

    def opened(task: str) -> bool:
        return any(pull.get("state") == "OPEN" for pull in cited(task))

    slow = SlowReads("/api/task", services.slow_read_s)

    def timed(request: Request, arrival: Arrival) -> AbstractContextManager[Any]:
        return slow.watch(request.path_params["id"], arrival)

    # Every write route, by path: the handler over the seams it needs and the kind of body it answers
    # (`contracts.api.registry.BODIES`). Each handler parses its body through the request model it is declared with.
    def started(task: str) -> bool:
        return started_by(api.history.engine, task)

    writes: dict[str, tuple[TaskWrite, str]] = {
        "/start": (
            lambda client, raw: start_task(client, raw, feed, assign, services.start_session, services.harnesses),
            "start",
        ),
        "/retire": (lambda client, raw: retire_task(client, raw, board), "retire"),
    }
    return [
        ReadRoute("/task/{id:path}", task, timed),
        ReadRoute("/task-records", task_records, params=frozenset({"ids"})),
        ReadRoute("/retired", retired, params=frozenset({"before", "fields", "limit", "milestone", "task"})),
        *(WriteRoute(path, ("POST",), guarded(kind, whole_body(handler))) for path, (handler, kind) in writes.items()),
        WriteRoute(
            "/tasks", ("PUT",), guarded("create", whole_body(lambda client, raw: create_task(client, raw, create, feed)))
        ),
        WriteRoute(
            "/tasks/{id:path}",
            ("PUT",),
            guarded(
                "task_put",
                lambda request: put_task(
                    client(request),
                    whole(request),
                    request.path_params["id"],
                    feed,
                    board,
                    services.take_over,
                    landed,
                    started=started,
                    opened=opened,
                    dispatch=services.dispatch,
                    entrypoint=services.entrypoint,
                ),
            ),
        ),
        WriteRoute(
            "/tasks/{id:path}",
            ("DELETE",),
            guarded(
                "task_delete",
                lambda request: delete_task(
                    client(request), whole(request) or b"{}", request.path_params["id"], feed, board
                ),
            ),
        ),
    ]
