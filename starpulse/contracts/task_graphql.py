"""The task GraphQL schema StarPulse serves at `/graphql`, and the check a view's stored document passes at config load.

The SDL is tracked in `schemas/tasks.graphql`; the server binds resolvers to it, config load only validates against it.
"""

from functools import cache
from pathlib import Path

from graphql import (
    DocumentNode,
    GraphQLError,
    GraphQLSchema,
    OperationDefinitionNode,
    OperationType,
    build_schema,
    parse,
    validate,
)

SDL = Path(__file__).parents[1] / "schemas" / "tasks.graphql"


@cache
def type_defs() -> str:
    return SDL.read_text()


@cache
def schema() -> GraphQLSchema:
    return build_schema(type_defs())


def _named(parsed: DocumentNode) -> list[OperationDefinitionNode]:
    return [node for node in parsed.definitions if isinstance(node, OperationDefinitionNode) and node.name]


@cache
def operations(document: str) -> frozenset[str]:
    """The names the document's operations declare; a document that does not parse declares none."""
    try:
        return frozenset(node.name.value for node in _named(parse(document)) if node.name)
    except GraphQLError:
        return frozenset()


def refusal(document: str) -> str | None:
    """Why `document` cannot be a view's stored query, or None: it must parse, hold a named query and pass the
    schema's validation rules."""
    try:
        parsed = parse(document)
    except GraphQLError as error:
        return error.message
    if not any(node.operation is OperationType.QUERY for node in _named(parsed)):
        return "holds no named query"
    errors = validate(schema(), parsed)
    return "; ".join(error.message for error in errors) or None
