"""The base model of every body of the API."""

from pydantic import BaseModel, ConfigDict


class _Api(BaseModel):
    """A body of the API: unknown fields are an error, so a producer that adds one must name it here."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
