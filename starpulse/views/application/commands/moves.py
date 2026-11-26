"""Move a task between lanes, dispatch a session to it and start a session on it."""

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from starpulse.board.model import criteria
from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.seam import (
    AssigneeWriter,
)
from starpulse.contracts.adapters import Move, StartFailedError
from starpulse.contracts.api.dto.requests import (
    StartRequest,
)
from starpulse.harness_telemetry.model.harnesses import Harnesses
from starpulse.views.application.commands.guard import (
    Who,
    held_task,
    not_held,
    with_request,
)

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass

lazy from starpulse.sessions.identity import same_session


#: Modes `POST /api/start` accepts; `interactive` is the Start-session default.
_START_MODES = frozenset({"interactive", "headless"})




def column_status(column: str) -> str:
    """The status a board column is written as; the board spells it as its lanes do."""
    return column.replace("_", " ").title()


def started_refusal(
    feed: BoardFeed, task: str, column: str, started: Callable[[str], bool]
) -> tuple[int, dict[str, str]] | None:
    """The 409 for a move into Ready, which holds only new work, of a task a session was dispatched to, else None."""
    if column == feed.roles.ready and started(task):
        return 409, {
            "error": f"{task} was started, and Ready holds only new work: move it to In Progress or Needs attention"
        }
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


#: Publishes the dispatch of a session to a task: `(task, session, replaces)`; whether the log appended it.
Dispatcher = Callable[[str, str, str], bool]


#: Names the `claude_code.entrypoint` of a session's record, empty when none runs under that id.
Entrypoint = Callable[[str], str]
#: Whether the harness confirms the session an id names is running.
Live = Callable[[str], bool]
#: The entrypoint of a Remote Control child, the session of a project thread.
REMOTE_CONTROL = "sdk-cli"


def remote_control_refusal(task: str, session: str, entrypoint: Entrypoint | None) -> tuple[int, dict[str, str]] | None:
    """The 409 for a claim of `task` by a project-thread session, else None: only a board-dispatched session works a task."""
    if session and entrypoint is not None and entrypoint(session) == REMOTE_CONTROL:
        return 409, {
            "error": f"{session} is a Remote Control project-thread session, and only a board-dispatched session works "
            f"{task}: file it Ready and the scheduler dispatches a VM session, which can then claim it"
        }
    return None


def dispatch_task(
    task: str,
    session: str,
    replaces: str,
    feed: BoardFeed,
    dispatch: Dispatcher | None,
    entrypoint: Entrypoint | None = None,
    live: Live | None = None,
) -> tuple[int, dict[str, str]]:
    """Publish the dispatch of `session` to `task`, which `PUT /api/tasks/{id}` names as an `assignee` change: the HTTP
    status and JSON body.

    The task actor pins the session and moves the lane; this writes nothing. It refuses, 409, what the actor
    would leave: a task another session holds (unless `replaces`, the `base` assignee, names that holder, whom the
    caller found dead), a session that already holds another task In Progress, and a task outside Ready, Needs
    attention and In Progress, and a session its harness cannot confirm live. A dispatch the event log did not append is a
    502, never a 202.
    """
    if dispatch is None:
        return 501, {"error": "this deployment publishes no dispatch events"}
    if refused := remote_control_refusal(task, session, entrypoint):
        return refused
    if live is not None and not live(session):
        return 409, {
            "error": f"{session} is not a session its harness confirms live: only a running session holds {task}"
        }
    if (agent := held_task(feed, task)) is None:
        return not_held(feed, task)
    roles, holder = feed.roles, str(agent.get("assignee") or "")
    if agent["state"] not in (roles.ready, roles.attention, roles.working):
        return 409, {
            "error": f"{task} is in {agent['state']}: a session is dispatched only to a Ready, Needs attention or In Progress task"
        }
    if holder and not same_session(holder, session) and not (replaces and same_session(holder, replaces)):
        return 409, {"error": f"{task} is already In Progress, held by {holder}"}
    others = [
        a["id"]
        for a in feed.open_tasks()
        if a["state"] == roles.working and same_session(a.get("assignee"), session) and a["id"] != task
    ]
    if others:
        return 409, {
            "error": f"this session already holds {others[0]} In Progress: park it, defer it or finish it before dispatching to {task}"
        }
    if not dispatch(task, session, replaces):
        return 502, {"error": f"the event log refused the dispatch of {session} to {task}: dispatch again"}
    return 202, {"task": task, "session": session}


def _start_refusal(feed: BoardFeed, task: str, agent: dict[str, Any]) -> str | None:
    """Why a session cannot start on `agent`, or None: it is held, outside the startable states, a Waiting task on an
    open dependency or a Start Criterion no event has met, or a Ready task whose dependencies are unresolved, which the task
    actor returns to Waiting, where the reaper ends the session."""
    startable = feed.roles.startable
    if agent["state"] == feed.roles.working:
        if holder := agent.get("assignee"):
            return (
                f"{task} is held by {holder}: a session starts an In Progress task only once its holder's session ended"
            )
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
        return (
            f"{on}: it starts once that is done"
            if waiting
            else f"{on}: the task actor returns it to {feed.roles.waiting}"
        )
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
