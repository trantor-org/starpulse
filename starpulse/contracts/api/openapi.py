"""The OpenAPI 3.1 document of every route the registry names, as `openapi.json` holds it."""

import json
import re
import types
import typing
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from starpulse.contracts.api.dto.errors import (
    ApiError,
    DeliveredElsewhere,
    NotHolder,
    SkillRefusal,
    StaleEdit,
    UnrecognisedUrl,
)
from starpulse.contracts.api.registry import ROUTES, Op, writes
from starpulse.contracts.api.schema import _Generator

#: Where the document is written, beside `api.schema.json`.
OPENAPI = Path(__file__).parents[2] / "schemas" / "openapi.json"

REF = "#/components/schemas/{model}"

#: Pydantic leaves a bound on a number union under its own name; JSON Schema names it like this.
_BOUNDS = {"gt": "exclusiveMinimum", "ge": "minimum", "lt": "exclusiveMaximum", "le": "maximum"}


def _bounded(node: Any) -> Any:
    if isinstance(node, dict):
        return {_BOUNDS.get(key, key): _bounded(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_bounded(item) for item in node]
    return node


def models_of(annotation: Any) -> list[type[BaseModel]]:
    """The models an annotation names, through unions."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    if isinstance(annotation, types.UnionType) or typing.get_origin(annotation) is typing.Union:
        return [model for arg in typing.get_args(annotation) for model in models_of(arg)]
    return []


def schema_of(model: type[BaseModel], mode: typing.Literal["validation", "serialization"]) -> dict[str, Any]:
    """`model`'s JSON schema as its component holds it: nested models are referenced, not inlined."""
    found = model.model_json_schema(by_alias=True, ref_template=REF, schema_generator=_Generator, mode=mode)
    found.pop("$defs", None)
    return _bounded(found)


def _ref(models: list[type[BaseModel]]) -> dict[str, Any]:
    # `anyOf`: answers such as `Restored` and `Retired` share a shape, so `oneOf` would match several branches
    refs = [{"$ref": REF.format(model=model.__name__)} for model in models]
    return refs[0] if len(refs) == 1 else {"anyOf": refs}


#: The refusals a write route answers under each status, which every write route declares beside its `4XX` union.
_REFUSED: dict[str, tuple[type[ApiError], ...]] = {
    "400": (ApiError, SkillRefusal, UnrecognisedUrl),
    "403": (ApiError, NotHolder),
    "409": (ApiError, SkillRefusal, StaleEdit, DeliveredElsewhere),
}


def _answers(op: Op, is_write: bool) -> dict[str, Any]:
    models = models_of(op.body)
    failed = [m for m in models if issubclass(m, ApiError)]
    passed = [m for m in models if m not in failed]
    if passed:
        schema = _ref(passed)
    elif op.media == "application/json":
        schema = {"type": "object"}
    else:
        schema = {"type": "string"}
    answers: dict[str, Any] = {
        status: {"description": "The answer", "content": {op.media: {"schema": schema}}} for status in op.status
    }
    for status, media, description in op.extra:
        answer = answers.setdefault(status, {"description": description, "content": {}})
        answer["content"][media] = {"schema": {"type": "string"} if media == "text/event-stream" else schema}
    if failed:  # each refusal extends `ApiError`, so a rich body also matches it: `anyOf`, never `oneOf`
        for status, bodies in _REFUSED.items() if is_write else ():
            answers[status] = {
                "description": "A refusal",
                "content": {"application/json": {"schema": _ref([m for m in failed if m in bodies])}},
            }
        answers["4XX"] = {
            "description": "A refusal",
            "content": {"application/json": {"schema": _ref(failed)}},
        }
    return answers


#: The tag of each route by the first segment of its path after `/api`, and what the tag groups.
TAGS = {
    "tasks": "One task and every write that moves or edits tasks",
    "board": "The board snapshot, its flows, machines, harnesses and history",
    "milestones": "Milestones",
    "docs": "Docs",
    "jobs": "Workflows, their runs, and Admin's settings (the scheduler, display and theme)",
    "ingest": "Events and webhooks that feed the board",
    "ops": "Health, metrics and the diagnostics of the server",
    "graphql": "Task reads by a GraphQL query, and the queries views store",
    "pages": "This document and its Swagger page",
}
_SEGMENT_TAG = {
    **dict.fromkeys(
        "task task-diff task-cost-to-go tasks task-records move start edit archive verdict rating "
        "miss restore take-over retired dispatch review complete reopen done search".split(),
        "tasks",
    ),
    **dict.fromkeys("snapshot flows machines harnesses history history-window".split(), "board"),
    **dict.fromkeys("jobs admin".split(), "jobs"),
    "intake": "ingest",
    **dict.fromkeys("doctor health steps".split(), "ops"),
    "milestones": "milestones",
    "docs": "docs",
    "openapi": "pages",
    "swagger": "pages",
    "metrics": "ops",
    **dict.fromkeys("graphql views".split(), "graphql"),
}


def _tag(path: str) -> str:
    return _SEGMENT_TAG[path.split("/")[2 if path.startswith("/api/") else 1]]


_TASK_PARAM = "The task's key, an alias it carries or its UUID."


def _path_parameter(name: str, path: str) -> dict[str, Any]:
    parameter: dict[str, Any] = {"name": name, "in": "path", "required": True, "schema": {"type": "string"}}
    if path.startswith(("/api/task/", "/api/tasks/")):
        parameter["description"] = _TASK_PARAM
    return parameter


def _operation(method: str, path: str, op: Op) -> dict[str, Any]:
    names = re.findall(r"\{(\w+)\}", path)
    parameters = (
        [_path_parameter(n, path) for n in names]
        + [{"name": n, "in": "query", "required": n in op.required, "schema": {"type": "string"}} for n in op.query]
        + [{"name": n, "in": "header", "required": True, "schema": {"type": "string"}} for n in op.headers]
    )
    operation: dict[str, Any] = {
        "summary": op.summary,
        "tags": [_tag(path)],
        "operationId": f"{method.lower()}_{re.sub(r'\W+', '_', path).strip('_')}",
    }
    if parameters:
        operation["parameters"] = parameters
    if isinstance(op.request, str):
        operation["requestBody"] = {"required": True, "content": {op.request: {"schema": {"type": "object"}}}}
    elif op.request is not None:
        operation["requestBody"] = {"required": True, "content": {"application/json": {"schema": _ref([op.request])}}}
    return {**operation, "responses": _answers(op, writes(method, path))}


@cache
def _document() -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for (method, path), op in ROUTES.items():
        paths.setdefault(path, {})[method.lower()] = _operation(method, path, op)
    requests = {m for op in ROUTES.values() if not isinstance(op.request, str) for m in models_of(op.request)}
    answered = {m for op in ROUTES.values() for m in models_of(op.body)}
    _, defs = models_json_schema(
        [(m, "validation") for m in requests] + [(m, "serialization") for m in answered - requests],
        by_alias=True,
        ref_template=REF,
        schema_generator=_Generator,
    )
    schemas = _bounded(dict(sorted(defs.get("$defs", {}).items())))
    return {
        "openapi": "3.1.0",
        "info": {"title": "StarPulse API", "version": "1", "description": "Every route `starpulse serve` answers."},
        "servers": [{"url": "/"}],
        "tags": [{"name": name, "description": text} for name, text in TAGS.items()],
        "paths": paths,
        "components": {"schemas": schemas},
    }


def document() -> dict[str, Any]:
    """The document: a copy, so a caller may change it."""
    return json.loads(render())


def render() -> str:
    return json.dumps(_document(), indent=2) + "\n"
