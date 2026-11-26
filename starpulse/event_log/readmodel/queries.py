"""The statements that read the Task tables: each is one index seek or one bounded index range, never a table scan.

`ReadModel` runs them; the tests EXPLAIN them. Archived Tasks stay out of every live query by the `archived = 0`
predicate the partial indexes carry, so the cost of a read follows the live board, not the whole History.
"""

from collections.abc import Collection
from typing import Any

from sqlalchemy import ColumnElement, Select, String, and_, cast, column, exists, false, func, or_, select, true

from starpulse.event_log.lane_events import done_lanes
from starpulse.event_log.readmodel.tables import criteria, tasks

SUMMARY = (
    tasks.c.id,
    tasks.c.seq,
    tasks.c.version,
    tasks.c.title,
    tasks.c.type,
    tasks.c.state,
    tasks.c.priority,
    tasks.c.milestone,
    tasks.c.assignee,
    tasks.c.released,
    tasks.c.archived,
    tasks.c.labels,
    tasks.c.updated_at,
)


#: What a card on the page draws that a delta summary leaves out; `meta` carries the Task's profile.
CARD = (*SUMMARY, tasks.c.description, tasks.c.final_summary, tasks.c.dependencies, tasks.c.references, tasks.c.meta)


def live(done: str, since: float) -> ColumnElement[bool]:
    """The live Tasks: unarchived, and either outside the done lanes or changed at or after `since`.

    The partial index `ix_starpulse_tasks_live_set` on `(archived, state, updated_at)` serves it, so a Done Task
    changed before `since` costs the read nothing.
    """
    lane = func.lower(func.replace(tasks.c.state, " ", "_"))
    return and_(tasks.c.archived == false(), or_(lane.not_in(done_lanes(done)), tasks.c.updated_at >= since))


def held_states() -> Select[Any]:
    """The states unarchived Tasks hold, Done ones of any age included."""
    return select(tasks.c.state).where(tasks.c.archived == false()).distinct()


def live_uuids(done: str, since: float) -> Select[Any]:
    """The UUIDs of the live Tasks (`live`)."""
    return select(tasks.c.uuid).where(live(done, since))


def held_done(done: str) -> Select[Any]:
    """The ids of unarchived Done Tasks of any age, in id order."""
    lane = func.lower(func.replace(tasks.c.state, " ", "_"))
    return select(tasks.c.id).where(tasks.c.archived == false(), lane.in_(done_lanes(done))).order_by(tasks.c.id)


def citing(url: str) -> Select[Any]:
    """The unarchived Tasks whose references hold the link `url`, with or without a trailing slash, in id order: a walk
    of the live index, bounded by the live board."""
    references = cast(tasks.c.references, String)
    cited = or_(references.contains(f'"{url}"', autoescape=True), references.contains(f'"{url}/"', autoescape=True))
    return select(tasks.c.id).where(tasks.c.archived == false(), cited).order_by(tasks.c.id)


def _cold(done: str, since: float) -> ColumnElement[bool]:
    lane = func.lower(func.replace(tasks.c.state, " ", "_"))
    return and_(
        tasks.c.archived == false(), lane.in_(done_lanes(done)), tasks.c.updated_at < since, tasks.c.milestone != ""
    )


def milestone_done(done: str, since: float) -> Select[Any]:
    """How many Done Tasks each milestone holds that `live` leaves out: unarchived and last changed before `since`."""
    return (
        select(tasks.c.milestone, func.count())
        .where(_cold(done, since))
        .group_by(tasks.c.milestone)
        .order_by(tasks.c.milestone)
    )


def cold_done(done: str, since: float, only: str | None = None) -> Select[Any]:
    """The Tasks `milestone_done` counts, each with its milestone; `only` limits them to one."""
    query = select(tasks.c.id, tasks.c.milestone).where(_cold(done, since)).order_by(tasks.c.id)
    return query if only is None else query.where(tasks.c.id == only)


def snapshot(done: str, since: float, only: str | None = None) -> Select[Any]:
    """The live Tasks (`live`), in id order; `only` limits them to one."""
    query = select(*CARD).where(live(done, since)).order_by(tasks.c.id)
    return query if only is None else query.where(tasks.c.id == only)


def live_criteria(done: str, since: float, only: str | None = None) -> Select[Any]:
    """The live Tasks' Acceptance Criteria, in task and number order; `only` limits them to one Task's."""
    query = (
        select(tasks.c.id.label("task_id"), criteria.c.kind, criteria.c.text, criteria.c.checked)
        .join(tasks, tasks.c.uuid == criteria.c.task_uuid)
        .where(live(done, since), criteria.c.kind == "ac")
        .order_by(tasks.c.id, criteria.c.n)
    )
    return query if only is None else query.where(tasks.c.id == only)


def with_field(field_column: str, value: object) -> Select[Any]:
    """The ids of unarchived Tasks whose declared, queried field's generated column equals `value`."""
    return select(tasks.c.id).where(tasks.c.archived == false(), column(field_column) == value).order_by(tasks.c.id)


def ready(state: str, done: str, only: str | None = None) -> Select[Any]:
    """The ids of unarchived Tasks in `state` none of whose dependencies is outside `done_lanes(done)`; with `only`,
    just that Task's id when it is one.

    `state` is a stored status (`Ready`) and `done` a lane id (`done`), as `lane_id` makes one; a dependency with no
    row blocks too: it is a Task the board has not imported yet.
    """
    dependency = func.json_each(tasks.c.dependencies).table_valued("value").alias("dependency")
    target = tasks.alias("target")
    blocked = (
        select(1)
        .select_from(dependency.outerjoin(target, target.c.id == dependency.c.value))
        .where(
            or_(
                target.c.id.is_(None),
                and_(
                    target.c.archived == false(),
                    func.lower(func.replace(target.c.state, " ", "_")).not_in(done_lanes(done)),
                ),
            )
        )
    )
    ready_tasks = select(tasks.c.id).where(
        tasks.c.archived == false(), tasks.c.state == state, ~exists(blocked.correlate(tasks))
    )
    return (ready_tasks if only is None else ready_tasks.where(tasks.c.id == only)).order_by(tasks.c.id)


def since(seq: int, limit: int) -> Select[Any]:
    """The Tasks changed after stream position `seq`, archived ones included, oldest change first."""
    return select(*SUMMARY).where(tasks.c.seq > seq).order_by(tasks.c.seq).limit(limit)


def archived(before: float | None, limit: int, milestone: str | None = None) -> Select[Any]:
    """The archived Tasks changed before `before` (None: any time), newest first: one range of the archive index;
    `milestone` keeps those of that milestone."""
    query = select(*SUMMARY).where(tasks.c.archived == true()).order_by(tasks.c.updated_at.desc(), tasks.c.id)
    if milestone is not None:
        query = query.where(tasks.c.milestone == milestone)
    return (query if before is None else query.where(tasks.c.updated_at < before)).limit(limit)


def archived_since(since: float) -> Select[Any]:
    """How many Tasks were archived at or after `since`: one range of the archive index."""
    return select(func.count()).where(tasks.c.archived == true(), tasks.c.updated_at >= since)


def settled_done(done: str, since: float, only: str | None = None) -> Select[Any]:
    """The archived Done Tasks changed at or after `since`, with their meta, in id order: one range of the archive index;
    `only` limits them to one."""
    lane = func.lower(func.replace(tasks.c.state, " ", "_"))
    query = (
        select(*SUMMARY, tasks.c.meta)
        .where(tasks.c.archived == true(), tasks.c.updated_at >= since, lane.in_(done_lanes(done)))
        .order_by(tasks.c.id)
    )
    return query if only is None else query.where(tasks.c.id == only)


def titled(ids: Collection[str] | None = None) -> Select[Any]:
    """Each Task's id, title, milestone, labels and meta, archived ones included, without the bodies a card draws; `ids`
    limits them to those Tasks, each one a primary-key seek."""
    query = select(tasks.c.id, tasks.c.title, tasks.c.milestone, tasks.c.labels, tasks.c.meta)
    return query if ids is None else query.where(tasks.c.id.in_(ids))


def dependencies_of(ids: Collection[str]) -> Select[Any]:
    """The id and dependencies of each Task `ids` names, archived ones included, each one a primary-key seek."""
    return select(tasks.c.id, tasks.c.dependencies).where(tasks.c.id.in_(ids))


def position() -> Select[Any]:
    """The stream position of the newest change: one seek on the `seq` index."""
    return select(func.max(tasks.c.seq))
