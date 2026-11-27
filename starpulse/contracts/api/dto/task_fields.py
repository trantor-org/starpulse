"""The task fields an edit names: `base` holds each as the record reads it, `changes` as the board's writer takes it."""

import re
from typing import Annotated, NotRequired, TypedDict

from pydantic import AfterValidator, ConfigDict, JsonValue, StrictBool, StringConstraints, WithJsonSchema

from starpulse.contracts.api.dto.brief import Brief
from starpulse.contracts.doc_links import PATTERN, doc_link

#: One `documentation` entry: a doc id (doc-N) or a file path, never a command's JSON reply.
DocLink = Annotated[
    str,
    AfterValidator(doc_link),
    WithJsonSchema(
        {"type": "string", "pattern": PATTERN, "description": "A doc id (doc-N) or a file path, never a JSON reply"}
    ),
]


def _title(value: str) -> str:
    if re.search(r"\bTASK-\d+\b", value):
        raise ValueError("names no TASK-N: link a related task with a dependency")
    if re.search(r"<[\w -]+>", value):
        raise ValueError("keeps no <placeholder>: name the outcome")
    return value


#: A task title: one to 80 characters naming the outcome, with no `TASK-N` and no `<placeholder>`.
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80), AfterValidator(_title)]


class ChecklistItem(TypedDict):
    """One acceptance criterion or definition-of-done item; an item without `n` is numbered after the highest given."""

    __pydantic_config__ = ConfigDict(extra="forbid")  # type: ignore[misc]  # pydantic reads it off a TypedDict
    text: str
    checked: StrictBool
    n: NotRequired[int]


class FrozenEdit(TypedDict, total=False):
    """Who froze the task, when and why."""

    __pydantic_config__ = ConfigDict(extra="forbid")  # type: ignore[misc]
    by: str | None
    at: str | float | None
    reason: str | None


class MemberKindSize(TypedDict):
    """One batch member's kind and size, each without its label prefix."""

    __pydantic_config__ = ConfigDict(extra="forbid")  # type: ignore[misc]
    kind: str
    size: str


class _Fields(TypedDict, total=False):
    description: str
    plan: str
    notes: str
    finalSummary: str
    needsAttention: str
    assignee: str
    type: str
    priority: str
    impact: str
    urgency: str
    tier: str
    milestone: str
    source: str
    adrNeeded: str
    duplicateSearch: str
    duplicateResolution: str
    follows: str
    profile: str
    status: str
    labels: list[str]
    dependencies: list[str]
    dependencyNeeds: list[str]
    references: list[str]
    modifiedFiles: list[str]
    acceptanceCriteria: list[ChecklistItem]
    definitionOfDone: list[ChecklistItem]
    actorMemory: dict[str, JsonValue]
    members: dict[str, MemberKindSize]
    frozen: FrozenEdit


class EditBase(_Fields, total=False):
    """The value each changed field had when the caller read it, a field the record holds as it holds it: a field the
    edit does not change may be named or left out."""

    __pydantic_config__ = ConfigDict(extra="ignore")  # type: ignore[misc]
    title: str
    documentation: list[str]


class Changes(_Fields, total=False):
    """An edit's fields by name, each as the board's writer takes it. `documentation` entries are links; `appendNotes`
    adds to the notes as they are when the write lands, and `planReason` is why the plan changes: neither has a base."""

    __pydantic_config__ = ConfigDict(extra="forbid")  # type: ignore[misc]
    title: Title
    documentation: list[DocLink] | None
    brief: Brief
    appendNotes: str
    planReason: str
