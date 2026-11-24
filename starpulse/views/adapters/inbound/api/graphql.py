"""`POST /graphql`: the task list and task detail queries over the read model, and the task subscription.

The tracked SDL (`schemas/tasks.graphql`) is bound with Ariadne and run by `ariadne.graphql()` from this endpoint, not
a mounted ASGI app. A resolver reads the feed on a request worker thread. The request-duration histogram carries the
operation name when a view's stored document declares it, else `other`.

A list answers with the stream position it was read at. A `taskChanges` subscription from a position is answered with an
event stream (graphql-sse's distinct connections mode): one `next` event for each task change after it, the document's
selection run on the change. A position the store no longer holds is answered with a 410 whose error code is `REREAD`.
"""

import json
import time
from inspect import isawaitable
from typing import Any

from anyio import from_thread, to_thread
from ariadne import ObjectType, QueryType, graphql, make_executable_schema
from graphql import (
    DocumentNode,
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    GraphQLError,
    GraphQLResolveInfo,
    OperationDefinitionNode,
    OperationType,
    execute,
    get_operation_ast,
    parse,
    validate,
)
from graphql.execution import get_argument_values, get_variable_values
from starlette.requests import Request
from starlette.responses import Response

from starpulse.contracts import task_graphql
from starpulse.contracts.adapters import Move
from starpulse.machine_engine.model.transitions import lane_id
from starpulse.views.adapters.inbound.api.answering import answer, on_worker, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import refused
from starpulse.views.adapters.outbound import request_durations
from starpulse.views.application.queries.responses import refuses_at_once, spend_response
from starpulse.views.model.encoding import encode

#: The largest document and variables a request may send, in bytes.
LIMIT = 65536

query = QueryType()
task = ObjectType("Task")


async def _worker(info: GraphQLResolveInfo, call: Any, *args: Any) -> Any:
    return await to_thread.run_sync(call, *args, limiter=info.context["workers"])


def _holds(agent: dict, text: str) -> bool:
    needle = text.lower()
    return any(needle in field.lower() for field in (agent["id"], agent["title"], *agent["labels"]))


@query.field("tasks")
async def _tasks(
    _: Any,
    info: GraphQLResolveInfo,
    filter: str | None = None,  # noqa: A002 - the schema's argument name
    source: str | None = None,
    lane: str | None = None,
    milestone: str | None = None,
) -> dict:
    position = info.context["api"].snapshots.position()  # before the read: a change after it is replayed, none is missed
    agents = await _worker(info, info.context["feed"].open_tasks)
    items = [
        agent
        for agent in agents
        if (filter is None or _holds(agent, filter))
        and (source is None or agent["source"] == source)
        and (lane is None or agent["state"] == lane_id(lane))
        and (milestone is None or agent["milestone"] == milestone)
    ]
    return {"position": position, "items": items}


@query.field("task")
async def _task(_: Any, info: GraphQLResolveInfo, id: str) -> dict | None:  # noqa: A002 - the schema's argument name
    return await _worker(info, info.context["feed"].task, id)


@task.field("lane")
def _lane(agent: dict, _: GraphQLResolveInfo) -> str:
    return agent["state"]


@task.field("movedAt")
def _moved_at(agent: dict, _: GraphQLResolveInfo) -> float:
    return agent["entered"]


@task.field("description")
async def _description(agent: dict, info: GraphQLResolveInfo) -> str:
    """A list's cards carry none: the record holds it."""
    if agent["description"]:
        return agent["description"]
    record = await _worker(info, info.context["feed"].task, agent["id"])
    return "" if record is None else record["description"]


@task.field("moves")
async def _moves(agent: dict, info: GraphQLResolveInfo) -> list[dict]:
    """A list's cards leave their moves unjudged: the record judges them, as judging every card's costs seconds."""
    record = await _worker(info, info.context["feed"].task, agent["id"])
    judged = {} if record is None else record["moves"]
    out = []
    for to, raw in judged.items():
        move = Move.read(raw)
        actors = [{"actor": actor, **verdict.model_dump()} for actor, verdict in move.actors.items()]
        out.append({"to": to, **move.model_dump(exclude={"actors"}), "actors": actors})
    return out


def _week(api: Any) -> tuple[bytes, int]:
    """The week's spend report of every task, kept under `spend` when the deployment keeps answers."""
    services, asked = api.services, {}

    def compute() -> tuple[bytes, int]:
        return spend_response(services.telemetry, asked, api.feed.keys, api.feed.titled, api.clock(), services.analytics)

    if services.answers is None:
        return compute()
    return services.answers.answer("spend", str([]), compute, lambda: refuses_at_once(services.telemetry, asked, api.clock()))


@task.field("spend")
async def _spend(agent: dict, info: GraphQLResolveInfo) -> list[dict]:
    body, status = await _worker(info, _week, info.context["api"])
    report = json.loads(body)
    if status != 200:
        raise GraphQLError(report.get("error", "the spend cannot be read"))
    return [row for row in report["spend"] if row["task"] == agent["id"]]


SCHEMA = make_executable_schema(task_graphql.type_defs(), query, task)


def _failed(request: Request, status: int, message: str) -> Response:
    return answer(request, encode("graphql", {"errors": [{"message": message}]}), status)


def _subscription(payload: Any) -> tuple[DocumentNode, OperationDefinitionNode] | None:
    """The document and the subscription it runs, when the request names one; anything else is the query path's."""
    if not (isinstance(payload, dict) and isinstance(payload.get("query"), str)):
        return None
    try:
        document = parse(payload["query"])
    except GraphQLError:
        return None
    operation = get_operation_ast(document, payload.get("operationName"))
    if operation is None or operation.operation is not OperationType.SUBSCRIPTION:
        return None
    return document, operation


def _root_field(document: DocumentNode, selection: Any) -> FieldNode:
    """The one field a subscription selects, behind any fragment spreads and inline fragments around it."""
    while not isinstance(selection, FieldNode):
        if isinstance(selection, FragmentSpreadNode):
            selection = next(d for d in document.definitions if isinstance(d, FragmentDefinitionNode) and d.name.value == selection.name.value)
        selection = selection.selection_set.selections[0]
    return selection


async def _render(document: DocumentNode, payload: dict, context: dict, change: dict) -> bytes:
    """One `next` event's body: the document's selection run on `change`."""
    result = execute(
        SCHEMA,
        document,
        root_value={"taskChanges": change},
        context_value=context,
        variable_values=payload.get("variables"),
        operation_name=payload.get("operationName"),
    )
    return encode("graphql", (await result if isawaitable(result) else result).formatted)


async def _follow(
    request: Request, payload: dict, found: tuple[DocumentNode, OperationDefinitionNode], context: dict
) -> Response:
    document, operation = found
    errors = validate(SCHEMA, document)
    variables = get_variable_values(SCHEMA, operation.variable_definitions or (), payload.get("variables") or {})
    if isinstance(variables, list):
        errors += variables
    if errors:
        return answer(request, encode("graphql", {"errors": [error.formatted for error in errors]}), 400)
    field = SCHEMA.subscription_type.fields["taskChanges"]  # type: ignore[union-attr]
    position = get_argument_values(field, _root_field(document, operation), variables)["from"]  # type: ignore[arg-type]

    def render(change: dict) -> str:
        return from_thread.run(_render, document, payload, context, change).decode()

    return await on_worker(request, lambda: seams(request).streams.task_changes(request, position, render))


async def _run(request: Request, operation: list[str]) -> Response:
    api = seams(request)
    refusal = refused(request)
    if refusal is not None:
        return refusal
    raw = await request.body()
    if len(raw) > LIMIT:
        return _failed(request, 413, f"a request is at most {LIMIT} bytes")
    try:
        payload = json.loads(raw)
    except ValueError:
        return _failed(request, 400, "the body is not JSON")
    if isinstance(payload, dict) and isinstance(payload.get("query"), str):
        name = payload.get("operationName")
        declared = {op for document in api.services.views.values() for op in task_graphql.operations(document)}
        operation[:] = [name if isinstance(name, str) and name in declared else "other"]
    context = {"feed": api.feed, "api": api, "workers": request.app.state.workers}
    if (found := _subscription(payload)) is not None:
        return await _follow(request, payload, found, context)
    succeeded, result = await graphql(SCHEMA, payload, context_value=context)
    return answer(request, encode("graphql", result), 200 if succeeded else 400)


async def serve(request: Request) -> Response:
    started = time.monotonic()
    operation = ["none"]
    client = request.headers.get("x-starpulse-client", "")
    try:
        return await _run(request, operation)
    finally:
        request_durations.observe("/graphql", frozenset(), b"", client, time.monotonic() - started, operation[0])


routes: list[ApiRoute] = [WriteRoute("/graphql", ("POST",), serve)]
