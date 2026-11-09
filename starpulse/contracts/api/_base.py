"""The base models of the API: a body the server sends, and a body the server takes."""

from pydantic import BaseModel, ConfigDict


class _Api(BaseModel):
    """A body the server sends: unknown fields are ignored, so a field the server adds never breaks a client pinned
    to an older StarPulse."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _Request(_Api):
    """A body the server takes: unknown fields are an error, so a misspelt field is refused instead of dropped."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
