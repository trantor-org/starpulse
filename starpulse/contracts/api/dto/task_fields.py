"""The task fields an edit names: `base` holds each as the record reads it, `changes` as the board's writer takes it."""

import re
from typing import Annotated, NotRequired, TypedDict

from pydantic import AfterValidator, ConfigDict, JsonValue, StrictBool, StringConstraints, ValidationInfo, WithJsonSchema

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


#: The task key a title may not name when the validation context gives no board's `keys`: a native board's default.
_DEFAULT_KEY = re.compile(r"task-\d+(?:\.\d+)*", re.I)


def _title(value: str, info: ValidationInfo) -> str:
    keys = (info.context or {}).get("keys")
    key = keys.key if keys is not None else _DEFAULT_KEY
    if match := re.search(rf"\b(?:{key.pattern})\b", value, key.flags):
        named = match.group().rsplit("-", 1)[0].upper()
        raise ValueError(f"names no {named}-N: link a related task with a dependency")
    if re.search(r"<[\w -]+>", value):
        raise ValueError("keeps no <placeholder>: name the outcome")
    return value


#: A task title: one to 80 characters naming the outcome, with no key of the board's tasks (`TASK-N` on a native board,
#: else the prefix of the `keys` the validation context names) and no `<placeholder>`.
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

    __pydantic_config__ = ConfigDict(extra="forbid")  # type: ignore[misc]
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
