"""The body each write route takes."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, ValidationInfo, field_validator, model_validator

from starpulse.contracts.api._base import _Request
from starpulse.contracts.api.dto.scheduler import QuietHours

#: The details a create takes besides its title, as one text value or a list of them. A create takes every one in its
#: single write: a second write to finish a task is refused as not on the board until the next scan places the card.
CREATE_TEXT = (
    "description",
    "priority",
    "impact",
    "urgency",
    "milestone",
    "profile",
    "assignee",
    "status",
    "type",
    "source",
    "adrNeeded",
    "duplicateSearch",
    "duplicateResolution",
)
CREATE_LISTS =("labels", "dependencies", "acceptanceCriteria", "references", "documentation", "definitionOfDone")
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


class MoveRequest(_Writer):
    """`POST /api/move`: move `task`, or each of `tasks` in one call, to the column `to`."""

    task: str | None = None
    tasks: list[NonBlank] | None = Field(None, min_length=1)
    to: str

    @model_validator(mode="after")
    def _not_both(self) -> MoveRequest:
        if self.task is not None and self.tasks is not None:
            raise ValueError("name task or tasks, not both")
        return self


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
    """`POST /api/edit`: change fields of `task`; `base` holds the value each changed field had when the page read it."""

    task: str
    base: dict[str, Any]
    changes: dict[str, Any]
    comment: str | None = None
    break_glass: bool = Field(False, alias="breakGlass")  # an editor import: its Events are marked break-glass (D5)


class ArchiveRequest(_Writer):
    """`POST /api/archive`: archive `task`, or each of `tasks` in one call, recording `reason` when it is not blank."""

    task: str | None = None
    tasks: list[NonBlank] | None = Field(None, min_length=1)
    reason: str | None = None

    @model_validator(mode="after")
    def _one_target(self) -> ArchiveRequest:
        if (self.task is None) == (self.tasks is None):
            raise ValueError("name exactly one of task and tasks")
        return self


class RestoreRequest(_Writer):
    """`POST /api/restore`: return the archived task `task` to the board's tasks, unchanged; the writer names who did."""

    task: str


class TakeOverRequest(_Request):
    """`POST /api/take-over`: flip the unattended task `task` to interactive; its workflow types nothing more."""

    task: str


class RetireRequest(_Request):
    """`POST /api/retire`: take the finished task `task` off the board into the history store's retired tasks."""

    task: str


class RetiredImportRequest(_Request):
    """`POST /api/retired/import`: keep the retired task file `name`, holding `text`, in the history store."""

    name: str
    text: str


class CompleteRequest(_Request):
    """`POST /api/complete`: move the Done task `task` into the board's completed tasks."""

    task: str


class ClaimRequest(_Writer):
    """`POST /api/claim`: move `task` to In Progress and record `session` as its assignee, an opaque string; the same
    assignee claiming again changes nothing, and an assignee already on another open claim is refused."""

    task: str


class ParkRequest(_Writer):
    """`POST /api/park`: pause `task` on exactly one reason, which picks the lane: `untilTask` (tasks that must reach
    Done, or `TASK-N#K` for one open criterion of a task) and `until` (criteria a check can observe) wait; `operator` (what only the operator can do) needs attention."""

    task: str
    untilTask: list[str] | None = None
    until: list[dict[str, Any]] | None = None
    operator: str | None = None
    comment: str | None = None


class ReviewRequest(_Writer):
    """`POST /api/review`: move `task` to Review, adding `references` and `summary` first so the configured rules judge
    the record the move would leave."""

    task: str
    references: list[str] | None = None
    summary: str | None = None
    comment: str | None = None


class CreateSpec(_Request):
    """One task a create files: its `title` and details, and an optional `ref` that a sibling in the same batch names
    as `ref:<label>` in its `dependencies`.

    Text is trimmed; list items are trimmed and blank ones dropped, or refused where the list must hold only text.
    `task`, `size` and `skill` are read and left unused by a create.
    """

    ref: str | None = None
    title: str
    description: str | None = None
    priority: str | None = None
    impact: str | None = None
    urgency: str | None = None
    milestone: str | None = None
    profile: str | None = None
    assignee: str | None = None
    status: str | None = None
    type: str | None = None
    source: str | None = None
    adrNeeded: str | None = None
    duplicateSearch: str | None = None
    duplicateResolution: str | None = None
    task: str | None = None
    size: str | None = None
    skill: str | None = None
    labels: list[str] | None = None
    dependencies: list[str] | None = None
    acceptanceCriteria: list[str] | None = None
    references: list[str] | None = None
    documentation: list[str] | None = None
    definitionOfDone: list[str] | None = None

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
    """`POST /api/tasks`: create a task in the lane `status` names or else the board's starting lane, stamped
    `created_by: <harness>:<session>`, or each of `tasks` in one call, each with its own title and details.
    """

    title: str | None = None
    tasks: list[CreateSpec] | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def _one_target(self) -> CreateRequest:
        if (self.title is None) == (self.tasks is None):
            raise ValueError("name exactly one of title and tasks")
        return self


class VerdictRequest(_Writer):
    """`POST /api/verdict`: record `verdict` (`pass` or `miss`) for `check` of `task`'s `## Post-merge Checks`.

    A `miss` names the task `fix` that repairs it; `evidence` is kept in the verdict's comment.
    """

    task: str
    check: str
    verdict: str
    evidence: str | None = None
    fix: str | None = None


class RatingRequest(_Writer):
    """`POST /api/rating`: record one change of `task`'s pass/fail rating: `pass`, `fail` with an optional `reason`, or
    `cleared`. Every change is kept; the latest one is the task's rating.
    """

    task: NonBlank
    verdict: Literal["pass", "fail", "cleared"]
    reason: str | None = Field(default=None, max_length=120)


class MissRequest(_Writer):
    """`POST /api/miss`: file the task `fix` and record `check` of `task` as missed, naming it, in one write."""

    task: str
    check: str
    fix: CreateSpec
    evidence: str | None = None
    reason: str | None = None


class MilestoneCreateRequest(_Request):
    """`POST /api/milestones`: open a milestone; only the title is required."""

    title: str
    outcome: str | None = None
    specs: list[str] | None = None
    adrs: list[str] | None = None
    retro: str | None = None


class MilestoneEditRequest(_Request):
    """`POST /api/milestones/edit`: replace the `title`, `outcome`, `specs`, `adrs` or `retro` `changes` names."""

    milestone: str
    changes: dict[str, Any]


class MilestoneArchiveRequest(_Request):
    """`POST /api/milestones/archive`: archive `milestone`."""

    milestone: str


class DocCreateRequest(_Request):
    """`POST /api/docs`: file a doc; only the title is required. `type` is `specification`, `guide`, `readme` or `other`."""

    title: str
    type: str | None = None
    folder: str | None = None
    body: str | None = None


class DocEditRequest(_Request):
    """`POST /api/docs/edit`: replace the `title`, `type` or `body` `changes` names."""

    doc: str
    changes: dict[str, Any]


class DocArchiveRequest(_Request):
    """`POST /api/docs/archive`: archive `doc`."""

    doc: str


class DocRestoreRequest(_Request):
    """`POST /api/docs/restore`: return the archived doc `doc` to `folder` under the board's docs (the docs folder
    itself when absent), unchanged."""

    doc: str
    folder: str | None = None


class WindowRequest(_Request):
    """`PUT /api/history-window`: set the shared history window."""

    hours: float


class SchedulerRequest(_Request):
    """`PUT /api/scheduler`: whether the scheduler admits tasks, which harness it starts on, and/or its quiet hours."""

    enabled: bool | None = None
    harness: str | None = None
    quietHours: QuietHours | None = None
