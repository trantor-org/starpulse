"""A task's stored link, as the link routes answer it."""

from typing import Literal

from pydantic import AwareDatetime, Field

from starpulse.contracts.api._base import _Api


class Link(_Api):
    """One stored link of a task, keyed by the task's UUID: `handle` is the task's current key, `url` the owning
    adapter's display form of `ref` (None: it renders none), `requested_by` the session that asked, `at` when the
    task actor wrote it and `event` the id of its `link-written` or `link-removed` event."""

    task: str
    handle: str
    role: Literal["delivers", "cites", "holds"]
    ref: str
    url: str | None = None
    requested_by: str = Field(alias="requestedBy")
    at: AwareDatetime
    event: str
