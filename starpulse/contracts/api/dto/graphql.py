"""`/graphql` and the views' stored queries."""

from typing import Any

from pydantic import Field, JsonValue, model_validator

from starpulse.contracts.api._base import _Api, _Request


class GraphqlRequest(_Request):
    """`POST /graphql`: one GraphQL document and the operation of it to run."""

    query: str = Field(description="The GraphQL document: a fragment and the named queries a view stores.")
    operationName: str | None = Field(None, description="The operation of the document to run.")
    variables: dict[str, JsonValue] | None = Field(None, description="The values of the operation's variables.")


class GraphqlError(_Api):
    """One error a query met, as the GraphQL over HTTP spec names its fields."""

    message: str
    locations: list[dict[str, int]] | None = None
    path: list[str | int] | None = None
    extensions: dict[str, Any] | None = Field(None, description="Machine-readable detail; `code` is `REREAD` for a lost stream position.")


class GraphqlResponse(_Api):
    """`POST /graphql`: the data the query asked for, and the errors it met; a query the schema refuses has errors only."""

    data: dict[str, Any] | None = None
    errors: list[GraphqlError] | None = None

    @model_validator(mode="after")
    def _answers(self) -> GraphqlResponse:
        if not self.model_fields_set:
            raise ValueError("a GraphQL response names data, errors or both")
        return self


class ViewShown(_Api):
    """`GET /api/views/<id>`: the one GraphQL document a view stores in `starpulse.toml`."""

    name: str
    query: str
