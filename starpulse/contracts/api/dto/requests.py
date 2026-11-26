"""The body each write route takes."""

from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    Field,
    StrictFloat,
    StrictInt,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from starpulse.contracts.api._base import _Request
from starpulse.contracts.api.dto.admin import Clock, Density, OpensOn, Scale, Theme
from starpulse.contracts.api.dto.machine_definition import MachineDefinition, PolicyRows
from starpulse.contracts.api.dto.scheduler import QuietHours
from starpulse.contracts.api.dto.task_fields import Changes, DocLink, EditBase, MemberKindSize
from starpulse.contracts.tiers import TIERS

#: The details a create takes besides its title, as one text value or a list of them. A create takes every one in its
#: single write: a second write to finish a task is refused as not on the board until the next scan places the card.
CREATE_TEXT = (
    "description",
    "notes",
    "priority",
    "impact",
    "urgency",
    "tier",
    "milestone",
    "profile",
    "assignee",
    "status",
    "type",
    "source",
    "adrNeeded",
    "duplicateSearch",
    "duplicateResolution",
    "follows",
)
CREATE_LISTS = ("labels", "dependencies", "acceptanceCriteria", "references", "documentation", "definitionOfDone")
#: The lists whose every item must be nonblank, rather than dropped when blank.
_CREATE_NONBLANK = ("acceptanceCriteria", "definitionOfDone")
_PRIORITIES = frozenset({"high", "medium", "low"})  # also the levels of Impact and Urgency


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


#: Text a write names that must hold something: a blank name is an error, not an absent one.
NonBlank = Annotated[str, AfterValidator(_nonblank)]

class _Writer(_Request):
    """The writer a board write names: `actor` is `operator` from the page and `agent` from a session; a write naming
    neither is `anonymous`. The `session` and `harness` it names land on the change's `board:lanes` row."""

    actor: NonBlank | None = None
    session: NonBlank | None = None
    harness: NonBlank | None = None


class StartRequest(_Request):
    """`POST /api/start`: start a session for `task` on `profile`; `harness` defaults to `claude`.

    `assignee` is the legacy name of `profile` and is read when `profile` is absent.
    """

    task: str
    profile: str | None = None
    assignee: str | None = None
    harness: str | None = None
    mode: str | None = None
    actor: NonBlank | None = None
    session: NonBlank | None = None


class EditRequest(_Writer):
    """An edit: change fields of the task; `base` holds the value each changed field had when the page read it."""

    task: str
    base: EditBase
    changes: Changes
    comment: str | None = None
    break_glass: bool = Field(False, alias="breakGlass")  # an editor import: its Events are marked break-glass (D5)
    request_key: str | None = Field(
        None,
        min_length=1,
        max_length=128,
        description="The client's key for this send: an edit sent again with it answers the first send's answer.",
    )


class Park(_Request):
    """Pause the task on exactly one reason, which picks the lane: `untilTask` (tasks that must reach Done, or
    `TASK-N#K` for one open criterion of a task) and `until` (event subjects an alert or a deploy emits) wait;
    `operator` (what only the operator can do) needs attention."""

    untilTask: list[str] | None = None
    until: list[str] | None = None
    operator: str | None = None


class TaskPutRequest(_Writer):
    """`PUT /api/tasks/{id}`: write the task over the `base` it read, or reopen, complete, restore, retire, take it over, park
    it, ask the task actor to freeze or unfreeze it or dispatch a session to it.

    An edit names `changes` (and `base`, the value each changed field had when read) or a `comment`. `changes` that
    name only an `assignee` dispatch that session to the task, which the task actor pins; the `base` assignee is the
    holder, found dead, whose lease the dispatch ends first. Otherwise the
    body names exactly one of `reopen` (the Done task goes back to In Progress, with this reason), `completed: true`
    (the Done task moves into the board's completed tasks), `archived: false` (the archived task returns to the
    board), `retired: true` (the finished task goes off the board into the history store's retired tasks),
    `interactive: true` (the unattended task is taken over), `park` (the held task pauses for the one
    reason it names, with the `comment` beside it), `freeze` (the task actor freezes the task in its lane, for this
    reason) and `unfreeze: true` (the task actor lifts the freeze; only the operator or the freezer may ask it).
    """

    base: EditBase = Field(default_factory=EditBase)
    changes: Changes = Field(default_factory=Changes)
    comment: str | None = None
    break_glass: bool = Field(False, alias="breakGlass")
    request_key: str | None = Field(None, min_length=1, max_length=128)
    reopen: NonBlank | None = None
    completed: Literal[True] | None = None
    archived: Literal[False] | None = None
    retired: Literal[True] | None = None
    interactive: Literal[True] | None = None
    park: Park | None = None
    freeze: NonBlank | None = None
    unfreeze: Literal[True] | None = None

    @model_validator(mode="after")
    def _one_write(self) -> TaskPutRequest:
        verbs = ("reopen", "completed", "archived", "retired", "interactive", "park", "freeze", "unfreeze")
        named = [name for name in verbs if getattr(self, name) is not None]
        if len(named) > 1 or (named and (self.changes or (self.comment and named != ["park"]))):
            raise ValueError(
                "name changes, or exactly one of reopen, completed, archived, retired, interactive, park, freeze and unfreeze"
            )
        return self


class TaskDeleteRequest(_Writer):
    """`DELETE /api/tasks/{id}`: archive the task, recording `reason` when it is not blank; the body is optional."""

    reason: str | None = None




class CreateSpec(_Request):
    """One task a create files: its `title` and details, and an optional `ref` that a sibling in the same batch names
    as `ref:<label>` in its `dependencies`.

    Text is trimmed; list items are trimmed and blank ones dropped, or refused where the list must hold only text.
    `task`, `size` and `skill` are read and left unused by a create.
    """

    ref: str | None = None
    title: str
    description: str | None = None
    notes: str | None = None
    priority: str | None = None
    impact: str | None = None
    urgency: str | None = None
    tier: str | None = None
    milestone: str | None = None
    profile: str | None = None
    assignee: str | None = None
    status: str | None = None
    type: str | None = None
    source: str | None = None
    adrNeeded: str | None = None
    duplicateSearch: str | None = None
    duplicateResolution: str | None = None
    follows: str | None = None
    task: str | None = None
    size: str | None = None
    skill: str | None = None
    labels: list[str] | None = None
    dependencies: list[str] | None = None
    acceptanceCriteria: list[str] | None = None
    references: list[str] | None = None
    documentation: list[DocLink] | None = None
    definitionOfDone: list[str] | None = None
    members: dict[str, MemberKindSize] | None = None

    @field_validator(*CREATE_TEXT)
    @classmethod
    def _trimmed(cls, value: str | None) -> str | None:
        return None if value is None else value.strip()

    @field_validator("priority", "impact", "urgency")
    @classmethod
    def _known_priority(cls, value: str | None) -> str | None:
        if value and value.lower() not in _PRIORITIES:
            raise ValueError("must be high, medium or low")
        return value and value.lower()

    @field_validator("tier")
    @classmethod
    def _known_tier(cls, value: str | None) -> str | None:
        if value and value.lower() not in TIERS:
            raise ValueError(f"must be one of {', '.join(TIERS)}")
        return value and value.lower()

    @field_validator(*CREATE_LISTS)
    @classmethod
    def _kept(cls, value: list[str] | None, info: ValidationInfo) -> list[str] | None:
        if value is None:
            return None
        kept = [item.strip() for item in value if item.strip()]
        if info.field_name in _CREATE_NONBLANK and len(kept) != len(value):
            raise ValueError("must be a list of nonblank text")
        return kept


class CreateRequest(_Writer, CreateSpec):
    """`PUT /api/tasks`: create a task in the lane `status` names or else the board's starting lane, stamped
    `created_by: <harness>:<session>`, or each of `tasks` in one call, each with its own title and details.
    """

    title: str | None = None
    tasks: list[CreateSpec] | None = Field(None, min_length=1)
    request_key: str | None = Field(
        None,
        min_length=1,
        max_length=128,
        description="The client's key for this send: a create sent again with it answers the first send's answer.",
    )

    @model_validator(mode="after")
    def _one_of_title_and_tasks(self) -> CreateRequest:
        if (self.title is None) == (self.tasks is None):
            raise ValueError("name exactly one of title and tasks")
        return self


class MilestoneCreateRequest(_Request):
    """`PUT /api/milestones`: open a milestone; only the title is required."""

    title: str
    outcome: str | None = None
    specs: list[str] | None = None
    adrs: list[str] | None = None
    retro: str | None = None


class MilestoneListRequest(_Request):
    """`POST /api/milestones`: list the open milestones. It takes no field."""


class MachineListRequest(_Request):
    """`POST /api/machines`: list the machines the board draws. It takes no field."""


class JobListRequest(_Request):
    """`POST /api/jobs`: list the workflows the runs adapters report. It takes no field."""


class MachineCreateRequest(_Request):
    """`PUT /api/machines`: create a machine from `definition`, a machine document, when no active machine has its name."""

    definition: MachineDefinition


class MachinePutRequest(_Request):
    """`PUT /api/machines/{name}`: activate `definition`, a machine document named `name`, over the version `base` (the
    `hash` of the machine detail the caller read). `policy`, the table rows of the whole board policy, is written and
    activated with it."""

    definition: MachineDefinition
    base: NonBlank
    policy: PolicyRows | None = None


class MilestonePutRequest(_Request):
    """`PUT /api/milestones/{id}`: replace the `title`, `outcome`, `specs`, `adrs` or `retro` named, if the milestone
    still reads `base`, the `revision` of the record the caller read."""

    base: NonBlank
    title: str | None = None
    outcome: str | None = None
    specs: list[str] | None = None
    adrs: list[str] | None = None
    retro: str | None = None


class DocCreateRequest(_Request):
    """`PUT /api/docs`: file a doc; only the title is required. `type` is `specification`, `guide`, `readme`, `postmortem` or `other`."""

    title: str
    type: str | None = None
    folder: str | None = None
    body: str | None = None


class DocListRequest(_Request):
    """`POST /api/docs`: list the docs `ids` names, bodies left out."""

    ids: list[str]


class DocPutRequest(_Request):
    """`PUT /api/docs/{id}`: replace the `title`, `type` or `body` named, if the doc still reads `base`, the `revision`
    of the record the caller read. `archived: false` first returns an archived doc to `folder` under the board's docs
    (the docs folder itself when absent), unchanged."""

    base: NonBlank
    title: str | None = None
    type: str | None = None
    body: str | None = None
    archived: Literal[False] | None = None
    folder: str | None = None


class WindowRequest(_Request):
    """`PUT /api/history-window`: set the shared history window."""

    hours: float


class SchedulerRequest(_Request):
    """The scheduler's part of `PUT /api/admin`: whether the scheduler admits tasks, which harness it starts on, its quiet
    hours, the selected harness's session cap and/or the cpu and memory limits."""

    enabled: bool | None = None
    harness: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    quietHours: QuietHours | None = None
    sessionCap: StrictInt | None = Field(
        default=None,
        gt=0,
        description="The selected harness's session cap, a whole number above zero that overrides `starpulse.toml`; null clears it.",
    )
    cpuLimit: StrictInt | StrictFloat | None = Field(
        default=None,
        gt=0,
        le=100,
        description="The cpu limit in percent, above 0 and at most 100, that overrides `starpulse.toml`; null clears it.",
    )
    memoryLimit: StrictInt | StrictFloat | None = Field(
        default=None,
        gt=0,
        le=100,
        description="The memory limit in percent, above 0 and at most 100, that overrides `starpulse.toml`; null clears it.",
    )


class DisplayPatch(_Request):
    """The display choices a write changes; a field left out keeps its value."""

    scale: Scale | None = None
    motion: bool | None = None
    view: OpensOn | None = None
    density: Density | None = None
    clock: Clock | None = None


class AdminRequest(SchedulerRequest):
    """`PUT /api/admin`: any of the scheduler's settings, a patch of the display choices and/or a whole theme; a field
    left out keeps its value."""

    display: DisplayPatch | None = None
    theme: Theme | None = None


class StepsRequest(_Request):
    """`POST /api/steps`: the seconds each step of one `command` run took, and its reuse hit or miss.

    `steps` names at most 100 steps (`[a-z0-9_.:-]`, 64 characters) with their seconds; `outcome` is how the run ended.
    """

    command: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.:-]{1,64}$")]
    outcome: Literal["ok", "failed"]
    steps: dict[Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.:-]{1,64}$")], Annotated[float, Field(ge=0)]] = (
        Field(default_factory=dict, max_length=100)
    )
    reuse: Literal["hit", "miss"] | None = None


#: `<kind>:<adapter instance>:<id>`: the core reads the kind and the instance, and only the owning adapter parses the id.
RefText = Annotated[str, StringConstraints(pattern=r"^(change|commit|session|repository|check):[a-z][a-z0-9-]*:.+$")]
#: The roles a session asks for; `holds` is written only by the task actor when it makes a session holder.
LinkRole = Literal["delivers", "cites"]


class LinkPutRequest(_Request):
    """`PUT /api/tasks/{id}/links`: the session `session` of `harness` asks the task actor to link the task to the
    pull request `ref` names, or `url` turns into through the configured forge. Give exactly one of `ref` and `url`."""

    role: LinkRole
    ref: RefText | None = None
    url: str | None = None
    session: NonBlank
    harness: NonBlank

    @model_validator(mode="after")
    def _one_target(self) -> "LinkPutRequest":
        if (self.ref is None) == (self.url is None):
            raise ValueError("give exactly one of ref and url")
        return self


class LinkDeleteRequest(_Request):
    """`DELETE /api/tasks/{id}/links`: the session `session` of `harness` asks the task actor to remove the `role` link
    to `ref`."""

    role: LinkRole
    ref: RefText
    session: NonBlank
    harness: NonBlank
