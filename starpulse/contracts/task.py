"""The one Task model: every field a request, an Event, a read-model row or a response carries about a task, typed once.

A surface (the create body, the edit body, the task response, the read-model columns, an Event payload) names a
task field by the name it has on the wire or in its table. `ALIASES` maps each name that is not the canonical one,
and `tests/unit/contracts/test_task_model.py` fails on a name or a type the model does not define.
"""

from typing import TypedDict

from pydantic import BaseModel, ConfigDict, JsonValue

from starpulse.contracts.api.dto.task import ClaimRelease
from starpulse.contracts.api.dto.task_fields import ChecklistItem, FrozenEdit, MemberKindSize, Title

__all__ = ["ALIASES", "EXTRA", "FORMS", "META", "Comment", "Task"]


class Comment(TypedDict):
    """One comment on a task: who wrote it, when and what."""

    at: float
    actor: str
    text: str


class Task(BaseModel):
    """A task, as the board stores it. Text a person writes (`description`, `plan`, `notes`, `final_summary`) stays prose."""

    model_config = ConfigDict(extra="forbid")

    id: str
    uuid: str
    title: Title
    description: str
    plan: str
    notes: str
    final_summary: str
    needs_attention: str
    status: str
    assignee: str
    profile: str
    type: str
    priority: str
    impact: str
    urgency: str
    tier: str
    milestone: str
    source: str
    adr_needed: str
    duplicate_search: str
    duplicate_resolution: str
    follows: str
    labels: list[str]
    dependencies: list[str]
    dependency_needs: list[str]
    references: list[str]
    documentation: list[str]
    modified_files: list[str]
    acceptance_criteria: list[ChecklistItem]
    definition_of_done: list[ChecklistItem]
    actor_memory: dict[str, JsonValue]
    members: dict[str, MemberKindSize]
    frozen: FrozenEdit
    released: ClaimRelease | None
    archived: bool
    archived_at: float | None
    comments: list[Comment]
    created_at: float
    updated_at: float


#: The names a write body gives a field other than its canonical one. `brief` is the input alias of `description`: a
#: create or an edit takes the typed brief, and the board stores the description it renders to.
_WRITE = {
    "brief": "description",
    "finalSummary": "final_summary",
    "needsAttention": "needs_attention",
    "adrNeeded": "adr_needed",
    "duplicateSearch": "duplicate_search",
    "duplicateResolution": "duplicate_resolution",
    "dependencyNeeds": "dependency_needs",
    "modifiedFiles": "modified_files",
    "acceptanceCriteria": "acceptance_criteria",
    "definitionOfDone": "definition_of_done",
    "actorMemory": "actor_memory",
}

#: Per surface, each name it gives a field other than its canonical one.
ALIASES: dict[str, dict[str, str]] = {
    "create": _WRITE,
    "edit": _WRITE,
    "response": {"state": "status", "criteria": "acceptance_criteria", "created": "created_at"},
    "column": {"state": "status"},
}

#: Per surface, the fields it holds that are not task data: a write's own controls, a view's derived values, a row's
#: bookkeeping.
EXTRA: dict[str, frozenset[str]] = {
    "create": frozenset({"ref", "task", "size", "skill", "duplicateQueries", "checkDuplicates", "blocks"}),
    "edit": frozenset({"appendNotes", "planReason"}),
    "response": frozenset(
        {
            "model", "session_activity", "prs", "delivered", "runs", "task", "steps", "trail", "active", "pause_reason",
            "readable", "skill", "interactive", "previous", "moves", "entered", "workable", "workable_since", "stored",
            "awaiting",
        }
    ),
    "column": frozenset({"seq", "version", "fields", "meta", "phase", "substate", "skill", "prs", "open_dependencies"}),
}

#: Per surface, the fields it takes in another form than the record holds them in, by design: a create takes criteria
#: as text where the record holds items, and a create or an edit takes the typed brief where the record holds the
#: description it renders to.
FORMS: dict[str, frozenset[str]] = {
    "create": frozenset({"brief", "acceptanceCriteria", "definitionOfDone"}),
    "edit": frozenset({"brief"}),
}

#: The keys of the read model's `meta` column, each with the canonical field it carries, or None while its field is
#: pending: no field slice has added it to `Task` yet. A key leaves this map when its field becomes a column.
META: dict[str, str | None] = {
    "profile": "profile",
    "impact": "impact",
    "urgency": "urgency",
    "tier": "tier",
    "source": "source",
    "needsAttention": "needs_attention",
    "follows": "follows",
    "adrNeeded": "adr_needed",
    "duplicateSearch": "duplicate_search",
    "duplicateResolution": "duplicate_resolution",
    "dependencyNeeds": "dependency_needs",
    "actorMemory": "actor_memory",
    "members": "members",
    "frozen": "frozen",
    "uuid": "uuid",
    "start_criteria": None,
    "createdBy": None,
    "aliases": None,
    "uuids": None,
}
