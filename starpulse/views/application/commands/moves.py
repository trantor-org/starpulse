"""Move a task between lanes, claim it for a session and start a session on it."""

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from starpulse.board.model import criteria
from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.seam import (
    AGENT,
    OPERATOR,
    TASK_ACTOR,
    AssigneeWriter,
    MoveWriter,
    TaskReleaser,
)
from starpulse.contracts.adapters import Move, StartFailedError
from starpulse.contracts.api.dto.requests import (
    ClaimRequest,
    MoveRequest,
    NonBlank,
    ReleaseRequest,
    StartRequest,
)
from starpulse.harness_telemetry.model.harnesses import Harnesses
from starpulse.views.application.commands.guard import (
    RELEASED_ASSIGNEE,
    Who,
    held_task,
    holder_refusal,
    not_held,
    record_written,
    who_of,
    with_request,
)

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass

logger = logging.getLogger(__name__)


#: Starts the session a `StartRequest` names; `move_task` calls it for the operator's move of an unheld task.
Starter = Callable[[StartRequest], tuple[int, dict[str, Any]]]

#: Modes `POST /api/start` accepts; `interactive` is the Start-session default.
_START_MODES = frozenset({"interactive", "headless"})


class _ClaimBody(ClaimRequest):
    """A claim names its session, the opaque string that holds the task."""

    session: NonBlank


@with_request(MoveRequest, "Moving a task")
def move_task(
    request: MoveRequest, feed: BoardFeed, writer: MoveWriter, start: Starter | None = None, *, started: Callable[[str], bool]
) -> tuple[int, dict[str, Any]]:
    """Move the task `request` names, or each of its `tasks`, to the column it names, through `writer`: the HTTP status
    and JSON body. A batch answers 200 with the tasks moved and each refused one's error, so one refusal leaves the
    others moved.

    The board machine's exits from the task's state decide which columns are offered; the writer decides which
    it accepts, so a guard that changed since the snapshot still refuses.

    The operator's move of one unheld task into the working state also starts a session through `start`, on the
    task's own profile: the answer names its `url`, or the `startError` that kept it from starting. A batch move starts none.

    A task `started` (it ever entered the working state) is refused a move into Ready, whoever asks: Ready holds only new work.
    """
    who = who_of(request)
    if request.task is not None:
        return _move_one(feed, request.task, request.to, who, writer, start, started)
    if request.tasks is None:
        return 400, {"error": "invalid request: task: Field required"}
    moved, refused, warned = [], {}, {}
    for task in request.tasks or ():
        status, body = _move_one(feed, task, request.to, who, writer, None, started)
        if status == 200:
            moved.append(task)
            if body.get("warnings"):
                warned[task] = body["warnings"]
        else:
            refused[task] = body["error"]
    return 200, {"moved": moved, "refused": refused, **({"warnings": warned} if warned else {})}


def _move_one(
    feed: BoardFeed, task: str, column: str, who: Who, writer: MoveWriter, start: Starter | None, started: Callable[[str], bool]
) -> tuple[int, dict[str, Any]]:
    """Move the `task` the board holds to `column` as `who` for `move_task`: the HTTP status and JSON body."""
    if (agent := held_task(feed, task)) is None:
        return not_held(feed, task)
    if (refused := started_refusal(feed, task, column, started)) is not None:
        return refused
    status, body = _move(feed, agent, task, column, who, writer)
    if status == 200 and start is not None and _dragged_unheld(feed, agent, column, who):
        start_status, session = start(StartRequest(task=task, profile=agent.get("model") or None))
        body = {**body, **({"url": session["url"]} if start_status == 200 else {"startError": session["error"]})}
    return status, body


def _dragged_unheld(feed: BoardFeed, agent: dict, column: str, who: Who) -> bool:
    """Whether the operator moved a task no session holds into the working state: the move that starts its session."""
    return who.actor == OPERATOR and column == feed.roles.working and _unheld(agent)


def _unheld(agent: dict) -> bool:
    return agent.get("assignee") in (None, "", RELEASED_ASSIGNEE)


def column_status(column: str) -> str:
    """The status a board column is written as; the board spells it as its lanes do."""
    return column.replace("_", " ").title()


def started_refusal(feed: BoardFeed, task: str, column: str, started: Callable[[str], bool]) -> tuple[int, dict[str, str]] | None:
    """The 409 for a move of a task that ever entered the working state into Ready, which holds only new work, else None."""
    if column == feed.roles.ready and started(task):
        return 409, {"error": f"{task} was started, and Ready holds only new work: move it to In Progress or Needs attention"}
    return None


def move_refusal(agent: dict, task: str, column: str, who: Who) -> tuple[int, dict[str, str]] | None:
    """The 409 for a move to `column` that the machine does not offer `who` from the task's state, else None."""
    moves = agent.get("moves", {})
    if column not in moves:
        offered = f"its moves are {', '.join(sorted(moves))}" if moves else "it has no moves"
        return 409, {"error": f"{task} cannot move from {agent['state']} to {column}: {offered}"}
    if not (move := Move.read(agent["moves"][column])).permits(who.actor):
        return 409, {"error": move.for_actor(who.actor).reason, "skill": move.skill}
    return None


def _move(
    feed: BoardFeed, agent: dict, task: str, column: str, who: Who, writer: MoveWriter, claiming: bool = False
) -> tuple[int, dict[str, str]]:
    """Move the held task `agent` to `column` as `who` through `writer`: the HTTP status and JSON body of the move."""
    if (refused := move_refusal(agent, task, column, who) or holder_refusal(feed, agent, task, who)) is not None:
        return refused
    return _write_move(feed, task, column, who, writer, claiming)


def _write_move(
    feed: BoardFeed, task: str, column: str, who: Who, writer: MoveWriter, claiming: bool = False
) -> tuple[int, dict[str, Any]]:
    """Write `task` into `column` as `who` through `writer`, unjudged by the machine: the HTTP status and JSON body.

    Only a `claiming` write hands the writer the session, which makes it the task's holder: a plain move, such as an
    answer's resume from another session, leaves the holder as it was."""
    status = column_status(column)
    written = record_written(
        feed,
        task,
        who,
        lambda: (
            writer(task, status, who.actor, who.session)
            if claiming and who.session
            else writer(task, status, who.actor)
        ),
    )
    if written.unavailable:
        return 501, {"error": written.output}
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {
        "ok": True,
        "task": task,
        "to": column,
        **({"warnings": list(written.warnings)} if written.warnings else {}),
        **({"advice": written.advice} if written.advice else {}),
    }


def _claimer(who: Who, agent: dict, working: str) -> Who:
    """`who` as the claim's writer: the task actor's when the machine names no agent writer for the move into `working`,
    so an agent session never moves its own task in."""
    if who.actor != AGENT or (raw := agent.get("moves", {}).get(working)) is None:
        return who
    return who if Move.read(raw).permits(AGENT) else who._replace(actor=TASK_ACTOR)


@with_request(_ClaimBody, "Claiming a task")
def claim_task(request: _ClaimBody, feed: BoardFeed, writer: MoveWriter) -> tuple[int, dict[str, str]]:
    """Move the task `request` names to In Progress holding the session it names: the HTTP status and JSON body.

    The holder is an opaque string. A task In Progress under another holder, or when the holder already has another
    task In Progress, is refused 409 naming the holder or the task. A task the feed shows In Progress held by no
    session, by its own task name (a label, never a session) or by this holder (its local id or its claude.ai URL) is
    adopted: the claim is written without a lane move, so a park the feed has not yet placed (a restart's replay) is
    still undone rather than answered 200 with the task left parked.
    """
    from starpulse.event_log.claude_sessions import same_holder  # noqa: PLC0415 - the transcript reader loads when a claim names a session

    task = request.task
    if (agent := held_task(feed, task)) is None:
        return not_held(feed, task)
    working = feed.roles.working
    who = _claimer(who_of(request), agent, working)
    named_for_task = str(agent.get("assignee")).casefold() == task.casefold()
    mine = same_holder(agent.get("assignee"), who.session)
    adopt = agent["state"] == working and (_unheld(agent) or named_for_task or mine)
    if agent["state"] == working and not adopt:
        return 409, {"error": f"{task} is already In Progress, held by {agent['assignee']}"}
    others = [
        a["id"]
        for a in feed.open_tasks()
        if a["state"] == working and same_holder(a.get("assignee"), who.session) and a["id"] != task
    ]
    if others:
        return 409, {
            "error": f"this session already holds {others[0]} In Progress: park it, defer it or finish it before "
            f"claiming {task}"
        }
    if adopt:
        status, body = _write_move(feed, task, working, who, writer, claiming=not mine)
    else:
        status, body = _move(feed, agent, task, working, who, writer, claiming=True)
    return (200, {**body, "assignee": who.session}) if status == 200 else (status, body)


@with_request(ReleaseRequest, "Releasing a claim")
def release_task(request: ReleaseRequest, feed: BoardFeed, release: TaskReleaser) -> tuple[int, dict[str, str]]:
    """End the claim on the task `request` names, whoever holds it: the HTTP status and JSON body.

    The task loses its assignee, records the session as released and keeps its lane, so the next claim adopts it. A task
    no session holds is refused 409; judging whether the holder is gone is the caller's.
    """
    task, who = request.task, who_of(request)
    if (agent := held_task(feed, task)) is None:
        return not_held(feed, task)
    state, holder = agent["state"], agent.get("assignee")
    if not holder or holder == RELEASED_ASSIGNEE:
        return 409, {"error": f"{task} holds no claim"}
    written = record_written(feed, task, who, lambda: release(task, state, session=holder, actor=who.actor))
    if not written.ok:
        return 409, {"error": written.output}
    return 200, {"task": task, "to": state, "releasedFrom": holder}


def _start_refusal(feed: BoardFeed, task: str, agent: dict[str, Any]) -> str | None:
    """Why a session cannot start on `agent`, or None: it is held, outside the startable states, a Waiting task on an
    open dependency or a Start Criterion no event has met, or a Ready task whose dependencies are unresolved, which the task
    actor returns to Waiting, where the reaper ends the session."""
    startable = feed.roles.startable
    if agent["state"] == feed.roles.working:
        if (holder := agent.get("assignee")) and holder != RELEASED_ASSIGNEE:
            return f"{task} is held by {holder}: a session starts an In Progress task only once its claim is released"
        return None
    if agent["state"] == feed.roles.review:
        return None  # a closed Review session reopens through a Resume start, which leaves the task in Review
    if agent["state"] not in startable:
        listed = [state for state in feed.roles.roles if state in startable]
        names = " or ".join(filter(None, [", ".join(listed[:-1]), *listed[-1:]]))
        return f"{task} is in {agent['state']}: a session starts only a {names} task"
    if agent["state"] not in (feed.roles.ready, feed.roles.waiting):
        return None
    waiting = agent["state"] == feed.roles.waiting
    open_dependencies = [dependency for dependency in agent.get("dependencies", ()) if not feed.is_done(dependency)]
    if open_dependencies:
        on = f"{task} is in {agent['state']} on {', '.join(open_dependencies)}"
        return f"{on}: it starts once that is done" if waiting else f"{on}: the task actor returns it to {feed.roles.waiting}"
    waits = criteria.subjects(agent.get("description", "")) if waiting else ()
    if not waits:
        return None
    return f"{task} is in {agent['state']} until {' or '.join(waits)}: it starts once the event arrives"


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

    A changed profile is saved through the guarded writer first, and the start names it too, since the service reads
    the task from a board feed that can still show the old profile. `harness` selects which configured harness opens
    the session; `mode` defaults to `interactive`. `at` is when the start began, so the page applies only a refused
    claim made after it.

    A task In Progress starts only when no session holds it: its claim was never made, the claim TTL released it, or
    its assignee is the released marker a release leaves. A Review task starts a Resume session: it reopens the
    session the task's pull request waits on and leaves the task in Review.
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
    if reason := _start_refusal(feed, task, agent):
        return 409, {"error": reason}
    at = clock()
    if profile != agent["model"] and not (written := assign(task, profile, **named)).ok:
        return 409, {"error": written.output, "skill": written.skill}
    reopen = {"verb": "Resume"} if agent["state"] == feed.roles.review else {}
    try:
        try:
            session = start_session(task, harness=harness, mode=mode, profile=profile, **reopen)
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


def release_closed(feed: BoardFeed, task: str, release: TaskReleaser, announce: Callable[[str], None]) -> bool:
    """End the claim a closed workflow held on `task`, leaving it in its lane for a session to start on; False when no
    session holds it."""
    if (agent := held_task(feed, task)) is None or agent.get("assignee") in (None, "", RELEASED_ASSIGNEE):
        return False
    state, holder = agent["state"], agent["assignee"]
    if not record_written(feed, task, Who(TASK_ACTOR, "", ""), lambda: release(task, state, session=holder, actor=TASK_ACTOR)).ok:
        return False
    try:
        announce(task)
    except Exception:
        logger.exception("workflow close: the released notice for %s failed", task)
    return True
