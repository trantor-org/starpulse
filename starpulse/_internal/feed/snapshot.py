"""The Board a feed saves beside the position it reflects, so a restart resumes instead of replaying."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel


class BoardSnapshot(BaseModel):
    SCHEMA_VERSION: ClassVar[int] = 1
    open: dict[str, dict[str, Any]]
    settled: dict[str, dict[str, Any]]
    assignees: dict[str, Any]
    pulls: dict[str, Any] = {}
    pull_answers: dict[str, Any] = {}
    cited: dict[str, Any] = {}
    source: dict[str, Any] = {}
