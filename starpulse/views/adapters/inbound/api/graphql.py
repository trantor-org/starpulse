"""`POST /graphql`: the task list and task detail queries over the read model, the ledger's occurrences, and the subscriptions.

The tracked SDL (`schemas/tasks.graphql`) is bound with Ariadne and run by `ariadne.graphql()` from this endpoint, not
a mounted ASGI app. A resolver reads the feed on a request worker thread. The request-duration histogram carries the
operation name when a view's stored document declares it, else the `root.child` fields it selects, else `other`.

A list answers with the stream position it was read at. A `taskChanges`, `jobChanges` or `schedulerChanges` subscription from a position is
answered with an event stream (graphql-sse's distinct connections mode): one `next` event for each change after it, the
document's selection run on the change. A position the store no longer holds is answered with a 410 whose error code is `REREAD`.

An `occurrenceChanges` subscription holds one event's ledger: its first `next` event is the newest page (`head: true`),
each later one the rows that changed, with the merge ledger's strip and pins whole. An event no workflow is tied to is answered with a 404.

A `health` subscription takes no position: its first `next` event is the server's readiness components, build id, restarting
announcement and clock, and each later one follows a change of the components, the build or the restart.
"""

import asyncio
import json
import math
import time
from functools import partial
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
    get_named_type,
    get_operation_ast,
    parse,
    validate,
)
from graphql.execution import get_argument_values, get_variable_values
from starlette.requests import Request
from starlette.responses import Response

from starpulse.board.model.view import phase_of, skill_of
from starpulse.contracts import task_graphql
from starpulse.contracts.adapters import Move
from starpulse.github.model.pulls import pull_url
from starpulse.machine_engine.model.transitions import lane_id
from starpulse.views.adapters.inbound.api.answering import answer, on_worker, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import refused
from starpulse.views.adapters.outbound import request_durations
from starpulse.views.application.queries.responses import PAGE_LIMIT, spend_response, task_pulls
from starpulse.views.model.encoding import encode, milestone_done, recent_settled

#: The largest document and variables a request may send, in bytes.
LIMIT = 65536
#: The most `root.child` fields an `operation` label names, so a query selecting many fields cannot mint a series.
_LABEL_FIELDS = 4

query = QueryType()
task = ObjectType("Task")
task_list = ObjectType("TaskList")
occurrence = ObjectType("Occurrence")
pull_request = ObjectType("PullRequest")
claim_release = ObjectType("ClaimRelease")
board = ObjectType("Board")


async def _worker(info: GraphQLResolveInfo, call: Any, *args: Any) -> Any:
    return await to_thread.run_sync(call, *args, limiter=info.context["workers"])


def _holds(agent: dict, text: str) -> bool:
    needle = text.lower()
    return any(needle in field.lower() for field in (agent["id"], agent["title"], *agent["labels"]))


@query.field("tasks")
async def _tasks(
    _: Any,
    info: GraphQLResolveInfo,
    filter: str | None = None,
    source: str | None = None,
    lane: str | None = None,
    milestone: str | None = None,
) -> dict:
    position = info.context[
        "api"
    ].snapshots.position()  # before the read: a change after it is replayed, none is missed
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


async def _done(parent: dict, info: GraphQLResolveInfo) -> dict:
    """The snapshot's account of the Done tasks off the board, read once per query however many fields ask."""
    if "done" not in parent:
        parent["done"] = asyncio.ensure_future(_read_done(info))
    return await parent["done"]


async def _read_done(info: GraphQLResolveInfo) -> dict:
    feed = info.context["feed"]
    return {**await _worker(info, feed.done_fields), "now": info.context["api"].clock(), "roles": {"done": feed.roles.done}}


@task_list.field("settled")
async def _settled(parent: dict, info: GraphQLResolveInfo) -> list[dict]:
    return [{"id": task_id, **entry} for task_id, entry in recent_settled(await _done(parent, info)).items()]


@task_list.field("milestoneDone")
async def _milestone_done(parent: dict, info: GraphQLResolveInfo) -> list[dict]:
    return [{"milestone": name, "done": count} for name, count in milestone_done(await _done(parent, info)).items()]


@task_list.field("archivedToday")
async def _archived_today(parent: dict, info: GraphQLResolveInfo) -> int:
    return (await _done(parent, info))["archived_today"]


@task_list.field("machineTasks")
async def _machine_tasks(_: dict, info: GraphQLResolveInfo) -> list[dict]:
    return [
        {"machine": machine, **agent} for machine, agent in await _worker(info, info.context["feed"].machine_agents)
    ]


_HISTORY_ONLY = frozenset({"id", "lanePath", "machinePath", "planRevisions", "events", "__typename"})


@query.field("task")
async def _task(_: Any, info: GraphQLResolveInfo, id: str) -> dict | None:
    """A selection of history fields alone reads lean: the page's hover asks for nothing the board's rules decorate, and
    their per-lane verdicts and file reads cost far more than the history query behind it."""
    selections = info.field_nodes[0].selection_set.selections if info.field_nodes[0].selection_set else ()
    lean = all(isinstance(node, FieldNode) and node.name.value in _HISTORY_ONLY for node in selections)
    return await _worker(info, partial(info.context["feed"].held, lean=lean), id)


@query.field("occurrences")
async def _occurrences(
    _: Any, info: GraphQLResolveInfo, event: str, before: float | None = None, limit: int = 20
) -> dict | None:
    if before is not None and not math.isfinite(before) or not 0 < limit <= PAGE_LIMIT:
        raise GraphQLError(f"occurrences takes a finite before and a limit from 1 to {PAGE_LIMIT}")
    return await _worker(info, info.context["feed"].ledger_rows, event, before, limit)


@occurrence.field("child")
def _child(row: dict, _: GraphQLResolveInfo) -> bool:
    return "appliedBy" in row


@query.field("board")
def _board(_: Any, __: GraphQLResolveInfo) -> dict:
    return {}


@board.field("columns")
def _columns(_: dict, info: GraphQLResolveInfo) -> list[dict]:
    return info.context["feed"].machines["board"]["states"]


@board.field("roles")
def _roles(_: dict, info: GraphQLResolveInfo) -> dict:
    return info.context["feed"].roles.wire()


def _link(link: dict) -> dict:
    return {**link, "routes": link.get("routes", {}), "skill": link.get("skill", "")}


@board.field("machines")
def _machines(_: dict, info: GraphQLResolveInfo) -> list[dict]:
    machines = info.context["feed"].machines
    names = ("board", *(name for name in machines if name != "board"))
    return [
        {**machines[name], "name": name, "submachines": [_link(link) for link in machines[name].get("submachines", ())]}
        for name in names
    ]


async def _runs(parent: dict, info: GraphQLResolveInfo) -> dict:
    """The jobs and the runs error, read once per query however many fields ask."""
    if "runs" not in parent:
        parent["runs"] = asyncio.ensure_future(_worker(info, info.context["feed"].run_list))
    return await parent["runs"]


@board.field("dags")
async def _dags(parent: dict, info: GraphQLResolveInfo) -> list[dict]:
    return (await _runs(parent, info))["dags"]


@board.field("error")
async def _runs_error(parent: dict, info: GraphQLResolveInfo) -> str | None:
    return (await _runs(parent, info))["error"]


@query.field("pull")
async def _pull(_: Any, info: GraphQLResolveInfo, repo: str, number: int) -> dict | None:
    found = await _worker(info, task_pulls, info.context["pulls"], [pull_url(repo, number)])
    return found[0] if found else None


@task.field("lane")
def _lane(agent: dict, _: GraphQLResolveInfo) -> str:
    return agent["state"]


@task.field("createdAt")
def _created_at(agent: dict, _: GraphQLResolveInfo) -> float:
    return agent["created"]


@task.field("movedAt")
def _moved_at(agent: dict, _: GraphQLResolveInfo) -> float:
    return agent["entered"]


async def _record(agent: dict, info: GraphQLResolveInfo, *, lean: bool = False) -> dict | None:
    """The task's record, read once per query however many fields ask: a list's cards leave out what it holds. A `lean`
    read leaves out the verdicts of the board's rules, which only `moves` and `readable` need."""
    records = info.context.setdefault("records", {})
    if (agent["id"], lean) not in records:
        read = info.context["feed"].held
        records[agent["id"], lean] = asyncio.ensure_future(_worker(info, lambda: read(agent["id"], lean=lean)))
    return await records[agent["id"], lean]


def _read_placing(feed: Any) -> dict:
    """The slice of the stored body a task's phase and interactive mark read: the machines with their rows, and the roles."""
    rows: dict[str, list[dict]] = {}
    for machine, agent in feed.machine_agents():
        rows.setdefault(machine, []).append(agent)
    flows = [{"name": name, "machine": machine, "agents": rows.get(name, [])} for name, machine in feed.machines.items()]
    return {"flows": flows, "roles": feed.roles.wire(), "interactive": feed.interactive()}


async def _placing(info: GraphQLResolveInfo) -> dict:
    """`_read_placing`, read once per query however many tasks ask."""
    context = info.context
    if "placing" not in context:
        context["placing"] = asyncio.ensure_future(_worker(info, _read_placing, context["feed"]))
    return await context["placing"]


@task.field("phase")
async def _phase(agent: dict, info: GraphQLResolveInfo) -> str | None:
    return phase_of(agent, await _placing(info))[0]


@task.field("substate")
async def _substate(agent: dict, info: GraphQLResolveInfo) -> str | None:
    return phase_of(agent, await _placing(info))[1]


@task.field("skill")
async def _skill(agent: dict, info: GraphQLResolveInfo) -> dict | None:
    _, substate, flow = phase_of(agent, await _placing(info))
    return skill_of(substate, flow)


@task.field("interactive")
async def _interactive(agent: dict, info: GraphQLResolveInfo) -> bool:
    return (await _placing(info))["interactive"].get(agent["id"], False)


@task.field("sessionActivity")
def _session_activity(agent: dict, _: GraphQLResolveInfo) -> dict | None:
    return agent.get("session_activity")


@task.field("criteria")
async def _criteria(agent: dict, info: GraphQLResolveInfo) -> list[dict]:
    record = await _record(agent, info, lean=True)
    return [] if record is None else record["criteria"]


@task.field("pauseReason")
async def _pause_reason(agent: dict, info: GraphQLResolveInfo) -> str:
    record = await _record(agent, info, lean=True)
    return "" if record is None else record["pause_reason"] or ""


@task.field("readable")
async def _readable(agent: dict, info: GraphQLResolveInfo) -> str:
    record = await _record(agent, info)
    return "" if record is None else record["readable"]


@claim_release.field("idle")
def _idle(released: dict, _: GraphQLResolveInfo) -> bool:
    return released.get("idle", False)


@task.field("description")
async def _description(agent: dict, info: GraphQLResolveInfo) -> str:
    """A list's cards carry none: the record holds it."""
    if agent["description"]:
        return agent["description"]
    record = await _record(agent, info)
    return "" if record is None else record["description"]


@task.field("moves")
async def _moves(agent: dict, info: GraphQLResolveInfo) -> list[dict]:
    """A list's cards leave their moves unjudged: the record judges them, as judging every card's costs seconds."""
    record = await _record(agent, info)
    judged = {} if record is None else record["moves"]
    out = []
    for to, raw in judged.items():
        move = Move.read(raw)
        actors = [{"actor": actor, **verdict.model_dump()} for actor, verdict in move.actors.items()]
        out.append({"to": to, **move.model_dump(exclude={"actors"}), "actors": actors})
    return out


def _week(api: Any, task: str) -> tuple[bytes, int]:
    """The task's week of spend, read from its sessions' fold rows and its peers' phase rows."""
    return spend_response(api.services.telemetry, task, {}, api.clock())


@task.field("spend")
async def _spend(agent: dict, info: GraphQLResolveInfo) -> list[dict]:
    body, status = await _worker(info, _week, info.context["api"], agent["id"])
    report = json.loads(body)
    if status != 200:
        raise GraphQLError(report.get("error", "the spend cannot be read"))
    return report["spend"]


@task.field("prs")
async def _prs(agent: dict, info: GraphQLResolveInfo) -> list[dict]:
    """The PR store's records of the pull requests the task cites: a lookup by key, no GitHub read."""
    context = info.context
    links = await _worker(info, context["feed"].cited, agent["id"])
    return await _worker(info, task_pulls, context["pulls"], links)


@pull_request.field("files")
def _files(record: dict, _: GraphQLResolveInfo) -> list[str] | None:
    return (record["detail"] or {}).get("files")


def _history_key(agent: dict, info: GraphQLResolveInfo) -> str:
    keys = info.context["feed"].keys
    return keys.canonical(agent["id"]) if keys else agent["id"]


@task.field("lanePath")
async def _lane_path(agent: dict, info: GraphQLResolveInfo) -> list[dict]:
    return await _worker(info, info.context["api"].history.lane_path, _history_key(agent, info))


@task.field("machinePath")
async def _machine_path(agent: dict, info: GraphQLResolveInfo, machine: str) -> dict:
    if machine not in info.context["feed"].machines:
        raise GraphQLError(f"unknown machine {machine}")
    path, steps = await _worker(info, info.context["api"].history.machine_path, _history_key(agent, info), machine)
    return {"path": path, "steps": steps}


@task.field("planRevisions")
async def _plan_revisions(agent: dict, info: GraphQLResolveInfo) -> int:
    return await _worker(info, info.context["api"].history.plan_revisions, _history_key(agent, info))


@task.field("events")
async def _events(agent: dict, info: GraphQLResolveInfo, since: float) -> list[dict]:
    return await _worker(
        info, info.context["api"].history.task_events, _history_key(agent, info), since, info.context["api"].clock()
    )


SCHEMA = make_executable_schema(
    task_graphql.type_defs(), query, task, task_list, occurrence, pull_request, claim_release, board
)


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
            selection = next(
                d
                for d in document.definitions
                if isinstance(d, FragmentDefinitionNode) and d.name.value == selection.name.value
            )
        selection = selection.selection_set.selections[0]
    return selection


async def _render(document: DocumentNode, payload: dict, context: dict, name: str, change: dict) -> bytes:
    """One `next` event's body: the document's selection run on `change`, the value of subscription field `name`."""
    result = execute(
        SCHEMA,
        document,
        root_value={name: change},
        context_value={**context},  # a copy: what a resolver caches in it lives for this change only
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
    selected = _root_field(document, operation)
    name = selected.name.value
    args = get_argument_values(SCHEMA.subscription_type.fields[name], selected, variables)  # type: ignore[union-attr,arg-type]

    def render(change: dict) -> str:
        return from_thread.run(_render, document, payload, context, name, change).decode()

    streams = seams(request).streams
    if name == "health":
        return await on_worker(request, lambda: streams.health(request, render))
    if name == "occurrenceChanges":
        return await on_worker(request, lambda: streams.ledger_changes(request, args["event"], render))
    follow = {"jobChanges": streams.job_changes, "schedulerChanges": streams.scheduler_changes}.get(
        name, streams.task_changes
    )
    return await on_worker(request, lambda: follow(request, args["from"], render))


def _label(payload: dict, declared: set[str]) -> str:
    """The metric's `operation`: the name a view declares, else the schema's `root.child` fields the operation selects
    (`task.spend`), never a client-chosen name; more than `_LABEL_FIELDS` of them name only the root fields, and an
    operation that selects none is `other`."""
    name = payload.get("operationName")
    if isinstance(name, str) and name in declared:
        return name
    try:
        operation = get_operation_ast(parse(payload["query"]), name if isinstance(name, str) else None)
    except GraphQLError:
        return "other"
    if operation is None:
        return "other"
    roots = {**SCHEMA.query_type.fields, **SCHEMA.subscription_type.fields}
    selected = [s for s in operation.selection_set.selections if isinstance(s, FieldNode) and s.name.value in roots]
    parts = []
    for root in selected:
        fields = getattr(get_named_type(roots[root.name.value].type), "fields", {})
        children = root.selection_set.selections if root.selection_set else []
        names = [c.name.value for c in children if isinstance(c, FieldNode) and c.name.value in fields]
        parts += [f"{root.name.value}.{c}" for c in names] or [root.name.value]
    if len(parts) > _LABEL_FIELDS:
        parts = [root.name.value for root in selected]
    return "+".join(sorted(set(parts))) or "other"


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
        declared = {op for document in api.services.views.values() for op in task_graphql.operations(document)}
        operation[:] = [_label(payload, declared)]
    context = {"feed": api.feed, "api": api, "pulls": api.services.pulls, "workers": request.app.state.workers}
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
