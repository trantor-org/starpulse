"""Move a task between lanes, claim it for a session and start a session on it."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import (
    OPERATOR,
    AssigneeWriter,
    MoveWriter,
)
from starpulse.contracts.adapters import Move, StartFailedError
from starpulse.contracts.api.dto.requests import (
    ClaimRequest,
    MoveRequest,
    NonBlank,
    StartRequest,
)
from starpulse.harness_telemetry.model.harnesses import Harnesses
from starpulse.views.application.commands.guard import Who, held_task, not_held, record_written, who_of, with_request

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass

logger = logging.getLogger(__name__)


#: Starts the session a `StartRequest` names; `move_task` calls it for the operator's move of an unheld task.
Starter = Callable[[StartRequest], tuple[int, dict[str, Any]]]

#: Modes `POST /api/start` accepts; `interactive` is the Start-session default.
_START_MODES = frozenset({"interactive", "headless"})
_RELEASED_ASSIGNEE = "released"  # the assignee a release leaves; it names no session


class _ClaimBody(ClaimRequest):
    """A claim names its session, the opaque string that holds the task."""

    session: NonBlank


@with_request(MoveRequest, "Moving a task")
def move_task(
    request: MoveRequest, feed: BoardFeed, writer: MoveWriter, start: Starter | None = None
) -> tuple[int, dict[str, Any]]:
    """Move the task `request` names, or each of its `tasks`, to the column it names, through `writer`: the HTTP status
    and JSON body. A batch answers 200 with the tasks moved and each refused one's error, so one refusal leaves the
    others moved.

    The board machine's exits from the task's state decide which columns are offered; the writer decides which
    it accepts, so a guard that changed since the snapshot still refuses.

    The operator's move of one unheld task into the working state also starts a session through `start`, on the
    task's own profile: the answer names its `url`, or the `startError` that kept it from starting. A batch move starts none.
    """
    who = who_of(request)
    if request.task is not None:
        return _move_one(feed, request.task, request.to, who, writer, start)
    if request.tasks is None:
        return 400, {"error": "invalid request: task: Field required"}
    moved, refused = [], {}
    for task in request.tasks or ():
        status, body = _move_one(feed, task, request.to, who, writer, None)
        if status == 200:
            moved.append(task)
        else:
            refused[task] = body["error"]
    return 200, {"moved": moved, "refused": refused}


def _move_one(
    feed: BoardFeed, task: str, column: str, who: Who, writer: MoveWriter, start: Starter | None
) -> tuple[int, dict[str, Any]]:
    """Move the `task` the board holds to `column` as `who` for `move_task`: the HTTP status and JSON body."""
    if (agent := held_task(feed, task)) is None:
        return not_held(feed, task)
    status, body = _move(feed, agent, task, column, who, writer)
    if status == 200 and start is not None and _dragged_unheld(feed, agent, column, who):
        started_status, started = start(StartRequest(task=task, profile=agent.get("model") or None))
        body = {**body, **({"url": started["url"]} if started_status == 200 else {"startError": started["error"]})}
    return status, body


def _dragged_unheld(feed: BoardFeed, agent: dict, column: str, who: Who) -> bool:
    """Whether the operator moved a task no session holds into the working state: the move that starts its session."""
    return who.actor == OPERATOR and column == feed.roles.working and not agent.get("assignee")


def column_status(column: str) -> str:
    """The status a board column is written as; the board spells it as its lanes do."""
    return column.replace("_", " ").title()


def move_refusal(agent: dict, task: str, column: str, who: Who) -> tuple[int, dict[str, str]] | None:
    """The 409 for a move to `column` that the machine does not offer `who` from the task's state, else None."""
    moves = agent.get("moves", {})
    if column not in moves:
        offered = f"its moves are {', '.join(sorted(moves))}" if moves else "it has no moves"
        return 409, {"error": f"{task} cannot move from {agent['state']} to {column}: {offered}"}
    if not (move := Move.model_validate(agent["moves"][column])).permits(who.actor):
        return 409, {"error": move.for_actor(who.actor).reason, "skill": move.skill}
    return None


def _move(
    feed: BoardFeed, agent: dict, task: str, column: str, who: Who, writer: MoveWriter
) -> tuple[int, dict[str, str]]:
    """Move the held task `agent` to `column` as `who` through `writer`: the HTTP status and JSON body of the move."""
    if (refused := move_refusal(agent, task, column, who)) is not None:
        return refused
    return _write_move(feed, task, column, who, writer)


def _write_move(feed: BoardFeed, task: str, column: str, who: Who, writer: MoveWriter) -> tuple[int, dict[str, str]]:
    """Write `task` into `column` as `who` through `writer`, unjudged by the machine: the HTTP status and JSON body."""
    status = column_status(column)
    written = record_written(
        feed,
        task,
        who,
        lambda: writer(task, status, who.actor, who.session) if who.session else writer(task, status, who.actor),
    )
    if written.unavailable:
        return 501, {"error": written.output}
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "to": column, **({"advice": written.advice} if written.advice else {})}


@with_request(_ClaimBody, "Claiming a task")
def claim_task(request: _ClaimBody, feed: BoardFeed, writer: MoveWriter) -> tuple[int, dict[str, str]]:
    """Move the task `request` names to In Progress holding the session it names: the HTTP status and JSON body.

    The holder is an opaque string. A task already In Progress under that holder answers 200 without a write; under
    another, or when the holder already has another task In Progress, it is refused 409 naming the holder or the task.
    A task In Progress held by no session is adopted: the holder is recorded without a move.
    """
    task, who = request.task, who_of(request)
    if (agent := held_task(feed, task)) is None:
        return not_held(feed, task)
    working = feed.roles.working
    held = {"task": task, "to": working, "assignee": who.session}
    adopt = agent["state"] == working and not agent.get("assignee")
    if agent["state"] == working and not adopt:
        if agent.get("assignee") == who.session:
            return 200, held
        return 409, {"error": f"{task} is already In Progress, held by {agent['assignee']}"}
    others = [a["id"] for a in feed.open_tasks() if a["state"] == working and a.get("assignee") == who.session]
    if others:
        return 409, {
            "error": f"this session already holds {others[0]} In Progress: park it, defer it or finish it before "
            f"claiming {task}"
        }
    if adopt:
        status, body = _write_move(feed, task, working, who, writer)
    else:
        status, body = _move(feed, agent, task, working, who, writer)
    return (200, {**body, "assignee": who.session}) if status == 200 else (status, body)


def start_requested(
    request: StartRequest,
    feed: BoardFeed,
    assign: AssigneeWriter,
    start_session: Callable[..., str] | None,
    harnesses: Harnesses | None = None,
    clock: Callable[[], float] = time.time,
) -> tuple[int, dict[str, Any]]:
    """Start a session for the task `request` names, on the profile and harness it names: the HTTP status and JSON
    body.

    A changed profile is saved through the guarded writer first, since the session-start service reads the
    profile from the task. `harness` selects which configured harness opens the session; `mode` defaults to
    `interactive`. `at` is when the start began, so the page applies only a refused claim made after it.

    A task In Progress starts only when no session holds it: its claim was never made, the claim TTL released it, or
    its assignee is the released marker a release leaves.
    """
    task = request.task
    profile = request.profile if request.profile is not None else request.assignee
    harness = "claude" if request.harness is None else request.harness
    mode = "interactive" if request.mode is None else request.mode
    named = {} if request.actor is None else {"actor": request.actor.strip()}
    if profile is None:
        return 400, {"error": 'a start needs {"task": "TASK-N", "profile": "@agent-<tier>-<effort>"}'}
    if not harness:
        return 400, {"error": "harness must be a non-empty name from agent-harnesses.toml"}
    if mode not in _START_MODES:
        return 400, {"error": 'mode must be "interactive" or "headless"'}
    if start_session is None:
        return 404, {"error": "no session-start service is configured (session_start_url)"}
    if harnesses is not None and harnesses.harnesses:
        if (chosen := harnesses.harnesses.get(harness)) is None:
            return 409, {"error": f"{harness} is not a configured harness"}
        if not chosen.sessions:
            return 409, {"error": chosen.reason or f"{harness} cannot start a session"}
    if (agent := held_task(feed, task)) is None:
        return not_held(feed, task)
    startable = feed.roles.startable
    if agent["state"] == feed.roles.working:
        if (holder := agent.get("assignee")) and holder != _RELEASED_ASSIGNEE:
            return 409, {
                "error": f"{task} is held by {holder}: a session starts an In Progress task only once its claim is released"
            }
    elif agent["state"] not in startable:
        listed = [state for state in feed.roles.roles if state in startable]
        names = " or ".join(filter(None, [", ".join(listed[:-1]), *listed[-1:]]))
        return 409, {"error": f"{task} is in {agent['state']}: a session starts only a {names} task"}
    at = clock()
    if profile != agent["model"] and not (written := assign(task, profile, **named)).ok:
        return 409, {"error": written.output, "skill": written.skill}
    try:
        try:
            session = start_session(task, harness=harness, mode=mode)
        except TypeError:
            session = start_session(task)  # a one-arg starter from before harness/mode
        return 200, {"task": task, "url": session, "at": at}
    except StartFailedError as exc:
        return 502, {"error": str(exc)}


@with_request(StartRequest, "Starting a session")
def start_task(
    request: StartRequest,
    feed: BoardFeed,
    assign: AssigneeWriter,
    start_session: Callable[..., str] | None,
    harnesses: Harnesses | None = None,
    clock: Callable[[], float] = time.time,
) -> tuple[int, dict[str, Any]]:
    """`POST /api/start`: `start_requested` for the request body a page or a client posts."""
    return start_requested(request, feed, assign, start_session, harnesses, clock)
