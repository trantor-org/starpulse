"""A Board task as a verb or a held-task stream reports it, read from a snapshot."""

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

lazy from starpulse.contracts.adapters import Move

#: Who `task move` moves as: the machine YAML's writers say which moves an agent may make.
AGENT = "agent"


def board_flow(snapshot: dict[str, Any]) -> dict[str, Any]:
    return next(flow for flow in snapshot["flows"] if flow["name"] == "board")


def _agent_moves(agent: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The verdict on each column as the agent meets it: a move the board machine leaves to others is refused. A
    stored card names its set of verdicts in `move_set`, which the snapshot's `move_sets` table holds."""
    return {
        column: Move.read(raw).for_actor(AGENT).model_dump(include={"allowed", "reason", "skill"})
        for column, raw in (agent.get("moves") or snapshot.get("move_sets", {}).get(agent.get("move_set"), {})).items()
    }


#: What the board says of a pull request whose checks keep a task out of the review lane.
_CHECKS_SAID = {"pending": "required checks not all passed", "failing": "has failing checks"}


def _review_held(
    moves: dict[str, dict[str, Any]], pulls: Iterable[dict[str, Any]], review: str | None
) -> dict[str, dict[str, Any]]:
    """`moves` with the review lane refused for every actor while a pull request the task cites has pending or failing
    checks: the verdict the write-time hook gives (`board_validate._not_green`), which the move set alone cannot see."""
    held = next((pull for pull in pulls if pull["checks"] in _CHECKS_SAID and not pull["merged"] and not pull["closed"]), None)
    if held is None or review not in moves:
        return moves
    reason = f"PR {held['repo']}#{held['number']} {_CHECKS_SAID[held['checks']]}"
    return {**moves, review: {**moves[review], "allowed": False, "reason": reason}}


def roles_of(snapshot: dict[str, Any]) -> SimpleNamespace:
    """The snapshot's state roles, each point an attribute: `roles_of(snapshot).done` is the State where work is done."""
    return SimpleNamespace(**snapshot["roles"])


def done_ids(snapshot: dict[str, Any]) -> set[str]:
    """The tasks a dependency no longer waits on: those in the done lane, those past their hot day (`cold_done`, held
    by a feed's own snapshot, never the stored one) and those settled as completed."""
    done = {task["id"] for task in board_flow(snapshot)["agents"] if task["state"] == roles_of(snapshot).done}
    done |= set(snapshot.get("cold_done", ()))
    return done | {task_id for task_id, entry in snapshot["settled"].items() if entry["state"] == "completed"}


def _stored_pull(pull: dict[str, Any]) -> dict[str, Any] | None:
    """A pull request as a task record stores it (repo, number, state and a check list, no url) in the shape a view
    reads; one with a url is kept as stored, one naming neither a url nor a repo and number is dropped."""
    if pull.get("url"):
        return pull
    if not (pull.get("repo") and pull.get("number")):
        return None
    state = pull.get("state")
    url = f"https://github.com/{pull['repo']}/pull/{pull['number']}"
    return {**pull, "url": url, "merged": state == "MERGED", "closed": state == "CLOSED", "checks": ""}


def cold_agent(task_id: str, record: dict[str, Any], done: str, entered: float | None = None) -> dict[str, Any]:
    """A cold done task as a snapshot agent, built from its board record (`GET /api/task`) for a verb to view whole:
    `entered` is when it entered its lane, and the record's stored pull requests ride as `pulls`."""
    pulls = [row for pull in record.get("pulls", []) if (row := _stored_pull(pull))]
    return {
        "id": task_id,
        "title": record["title"],
        "state": done,
        "model": record["profile"],
        "profile": record["profile"],
        "milestone": record["milestone"],
        "type": record["type"],
        "impact": record.get("impact", ""),
        "urgency": record.get("urgency", ""),
        "source": record.get("source", ""),
        "follows": record.get("follows", ""),
        "labels": record["labels"],
        "dependencies": record["dependencies"],
        "criteria": [{"text": item["text"], "checked": item["checked"]} for item in record["acceptanceCriteria"]],
        "entered": entered,
        "prs": [pull["url"] for pull in pulls],
        "pulls": pulls,
        "moves": {},
        "description": record["description"],
    }


def _newest(snapshot: dict[str, Any], flow: str, task: str) -> dict[str, Any] | None:
    """`task`'s newest row in machine `flow`, the earlier on a tie; None when the machine holds none."""
    machine = next((f for f in snapshot["flows"] if f["name"] == flow), None)
    rows = [a for a in machine["agents"] if a.get("task") == task] if machine else []
    return max(rows, key=lambda a: a.get("active") or 0, default=None)


def _holding(snapshot: dict[str, Any], links: list[dict[str, Any]], task: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The link among `links` whose submachine holds `task` in its newest row, and that row."""
    held = [(link, row) for link in links if (row := _newest(snapshot, link["machine"], task))]
    return max(held, key=lambda pair: pair[1].get("active") or 0, default=None)


def phase_of(agent: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """An In Progress task's `(phase, substate, flow)`, picked as the kanban card's `climb` does: the newest row among
    the submachines its In Progress row's state links, else among all the In Progress machine links, names the phase
    (that link's state), the substate (that row's state) and the flow. A task held by no submachine reads the In
    Progress row's state alone."""
    if agent["state"] != roles_of(snapshot).working:
        return None, None, None
    inner = board_flow(snapshot)["machine"].get("submachines") or [{}]
    machine = next((f for f in snapshot["flows"] if f["name"] == inner[0].get("machine")), None)
    if machine is None:
        return None, None, None
    row = _newest(snapshot, machine["name"], agent["id"])
    links = [link for link in machine["machine"].get("submachines", []) if link["machine"] != machine["name"]]
    held = _holding(snapshot, [link for link in links if row and link["state"] == row["state"]], agent["id"]) or _holding(snapshot, links, agent["id"])
    if held is None:
        return (row["state"], None, None) if row else (None, None, None)
    link, held_row = held
    return link["state"], held_row["state"], next(f for f in snapshot["flows"] if f["name"] == link["machine"])


def skill_of(substate: str | None, flow: dict[str, Any] | None) -> dict[str, Any] | None:
    """The skill a held task is in: its machine's states in order, the state it holds, and the next edge its machine declares."""
    if flow is None:
        return None
    return {
        "name": flow["name"],
        "states": [state["id"] for state in flow["machine"]["states"]],
        "current": substate,
        "next": flow["machine"].get("next"),
    }


def _lane(agent: dict[str, Any], phase: str | None) -> str:
    """The lane a task reads in: a task whose In Progress phase is `parked` waits, whatever lane the board still holds."""
    return "waiting" if agent["state"] == "in_progress" and phase == "parked" else agent["state"]


#: The Deliver substates a pull request is open in, past the one that opens it; `review_fix` is every phase after.
_OPENED = ("pr_opened", "ci_green", "pr_ready")


def _unlinked(agent: dict[str, Any], phase: str | None, substate: str | None) -> str:
    """What a task read says of an In Progress task whose holder ran deliver and that has no `delivers` link: its pull request is on no task read."""
    ran = phase == "review_fix" or (phase == "deliver" and substate in _OPENED)
    return "" if not ran or agent.get("delivered") else f"{agent['id']} ran deliver and has no `delivers` link: its pull request is on no task until a link is written."


def task_view(agent: dict[str, Any], snapshot: dict[str, Any], done: set[str] | None = None) -> dict[str, Any]:
    """A Board task as a verb reports it. It waits on each dependency not in `done`, read from `snapshot` when absent:
    a caller viewing many tasks passes it once rather than rescanning the board per task. A Done task of the snapshot
    is a slim card with no dependencies, pulls or moves: `task show` reads its record instead."""
    pulls = {pull["url"]: pull for pull in [*snapshot["pulls"].get(agent["id"], []), *agent.get("pulls", [])]}
    if done is None:
        done = done_ids(snapshot)
    phase, substate, flow = phase_of(agent, snapshot)
    entered = agent.get("entered")
    dependencies = agent.get("dependencies", [])
    return {
        "id": agent["id"],
        "title": agent["title"],
        "lane": _lane(agent, phase),
        "phase": phase,
        "substate": substate,
        "skill": skill_of(substate, flow),
        "interactive": snapshot.get("interactive", {}).get(agent["id"], False),
        "done_at": datetime.fromtimestamp(entered, UTC).isoformat() if agent["state"] == roles_of(snapshot).done and entered else None,
        "profile": agent["model"],
        "assignee": agent.get("assignee", ""),
        "milestone": agent["milestone"],
        "type": agent.get("type", ""),
        "impact": agent.get("impact", ""),
        "urgency": agent.get("urgency", ""),
        "labels": agent["labels"],
        "dependencies": dependencies,
        "waiting_on": [dependency for dependency in dependencies if dependency not in done],
        "criteria": agent.get("criteria", []),
        "pause_reason": agent.get("pause_reason", ""),
        "readable": agent.get("readable", ""),
        "unlinked": _unlinked(agent, phase, substate),
        "source": agent.get("source", ""),
        "follows": agent.get("follows", ""),
        "prs": [pulls.get(url, {"url": url}) for url in agent.get("prs", [])],
        "moves": _review_held(_agent_moves(agent, snapshot), pulls.values(), roles_of(snapshot).review),
        "released": agent.get("released"),
        "frozen": agent.get("frozen"),
    }


def board_columns(
    snapshot: dict[str, Any], kept: Callable[[dict[str, Any]], bool], state: str | None = None
) -> dict[str, Any]:
    """Each Board column, or only `state`'s, with the tasks in it that `kept` keeps."""
    board = board_flow(snapshot)
    done = done_ids(snapshot)
    return {
        "columns": [
            {
                "state": column["id"],
                "name": column["name"],
                "tasks": [
                    view
                    for a in board["agents"]
                    if kept(a)
                    for view in [task_view(a, snapshot, done)]
                    if view["lane"] == column["id"]
                ],
            }
            for column in board["machine"]["states"]
            if not state or column["id"] == state
        ]
    }
