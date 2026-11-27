"""A card's derived fields, restated onto its `starpulse_tasks` row in the transaction that changed what they derive from, so
a list reads them with no resolver pass. They leave `seq` alone: the machine stream has no Task Event to number."""

from collections.abc import Collection, Mapping
from typing import Any

from sqlalchemy import Connection, bindparam, func, select, true, update

from starpulse.event_log.lane_events import done_lanes
from starpulse.event_log.readmodel.tables import machine_tasks, tasks
from starpulse.machine_engine.model.phase import phase_of
from starpulse.machine_engine.model.state_roles import StateRoles
from starpulse.machine_engine.model.transitions import lane_id

#: The `starpulse_tasks` columns these functions write: derived, so a fold neither reads nor writes them.
STORED = ("phase", "substate", "skill", "prs", "open_dependencies")


def restate_phase(db: Connection, touched: Collection[str], drawn: Mapping[str, dict] | None, roles: StateRoles | None) -> None:
    """Set each of `touched`'s phase, substate and skill flow from the machine rows it holds; null off the working lane.
    Nothing for a projector built with no machines to read them from."""
    if not touched or drawn is None or roles is None:
        return
    touched = list(touched)
    held = {row.id: row.state for row in db.execute(select(tasks.c.id, tasks.c.state).where(tasks.c.id.in_(touched)))}
    if not held:
        return
    agents: dict[str, list[dict]] = {name: [] for name in drawn}
    for machine, agent in db.execute(select(machine_tasks.c.machine, machine_tasks.c.agent).where(machine_tasks.c.task.in_(list(held)))):
        if machine in agents:
            agents[machine].append(agent)
    snapshot = {"flows": [{"name": name, "machine": machine, "agents": agents[name]} for name, machine in drawn.items()], "roles": roles.wire()}
    values = []
    for task, state in held.items():
        phase, substate, flow = phase_of({"id": task, "state": lane_id(state)}, snapshot)
        values.append({"task": task, "b_phase": phase, "b_substate": substate, "b_skill": flow and flow["name"]})
    db.execute(
        update(tasks).where(tasks.c.id == bindparam("task")).values(phase=bindparam("b_phase"), substate=bindparam("b_substate"), skill=bindparam("b_skill")),
        values,
    )


def restate_open_dependencies(db: Connection, touched: Collection[str], roles: StateRoles) -> None:
    """Set the open-dependency count of each of `touched` and of each task depending on one: the dependencies neither in a
    done lane nor archived, a dependency with no row counting open (a task the board has not imported yet), as `ready` reads it."""
    if not touched:
        return
    touched = list(touched)
    listed = func.json_each(tasks.c.dependencies).table_valued("value").alias("dependency")
    dependents = select(tasks.c.id).join(listed, true()).where(listed.c.value.in_(touched))
    affected = {row.id: row.dependencies or [] for row in db.execute(select(tasks.c.id, tasks.c.dependencies).where(tasks.c.id.in_(touched) | tasks.c.id.in_(dependents)))}
    named = {dependency for dependencies in affected.values() for dependency in dependencies}
    targets = {row.id: row for row in db.execute(select(tasks.c.id, tasks.c.state, tasks.c.archived).where(tasks.c.id.in_(named)))}
    done = done_lanes(roles.done)

    def is_open(dependency: str) -> bool:
        target = targets.get(dependency)
        return target is None or (not target.archived and lane_id(target.state) not in done)

    if affected:
        db.execute(
            update(tasks).where(tasks.c.id == bindparam("task")).values(open_dependencies=bindparam("b_open")),
            [{"task": task, "b_open": sum(map(is_open, dependencies))} for task, dependencies in affected.items()],
        )


def restate(db: Connection, touched: Collection[str], drawn: Mapping[str, Any] | None, roles: StateRoles | None) -> None:
    """Both restatements; nothing for a projector built with no machines to read them from."""
    if drawn is None or roles is None:
        return
    restate_phase(db, touched, drawn, roles)
    restate_open_dependencies(db, touched, roles)


def store_prs(db: Connection, prs: Mapping[str, list[dict[str, Any]]]) -> None:
    """Set the pull requests each task's row holds: its card's scalar fields, as the store holds them when it is told."""
    if prs:
        db.execute(
            update(tasks).where(tasks.c.id == bindparam("task")).values(prs=bindparam("b_prs")),
            [{"task": task, "b_prs": found} for task, found in prs.items()],
        )
