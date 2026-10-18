"""The cue and the pull a flow shows."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from starpulse.contracts.api._base import _Api


class Cue(_Api):
    """A DAG that runs on the same trigger as a Board event's writer but writes no lane itself."""

    dag: str
    event: str
    state: str
    on: str
    resolves: Literal["forced", "next"] | None = Field(
        default=None,
        description="How a failed run of the DAG clears: `forced` only on a green forced rerun, `next` on the DAG's "
        "next green run.",
    )
    grace: int = Field(
        default=300,
        description="Seconds after the event a run of the DAG may take to start before the Ledger draws the merge "
        "overdue.",
    )


class Pull(_Api):
    """One pull request a task cites, as GitHub last answered the server."""

    number: int
    url: str
    checks: Literal["pass", "failing", "pending", "none"] = Field(description="The head commit's check rollup.")
    merged: bool
    merge_sha: str | None = Field(description="The merge commit's SHA; null until the PR merges.")
    merged_at: str | None = Field(description="When the PR merged, ISO 8601 UTC; null until it does.")
    threads: int = Field(description="Unresolved review threads.")
    behind_main: int | None = Field(
        default=None, description="Commits `main` holds that the PR's head lacks; null once the head branch is gone."
    )
    stale: bool = Field(description="True when the last read failed and this is the read before it.")
