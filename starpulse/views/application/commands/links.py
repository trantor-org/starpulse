"""A task's pull request links: the task actor stores one only on the request of the session that holds the task."""

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, NamedTuple

from starpulse.board.adapters.item_uuid import stamp_task
from starpulse.board.adapters.task_links import DeliveredElsewhere, StoredLink, TaskLinks
from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.seam import TaskReader
from starpulse.contracts.adapters import ChangeRef
from starpulse.contracts.api.dto.requests import LinkDeleteRequest, LinkPutRequest
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore, StaleVersion
from starpulse.pulls.adapters.outbound.github import GitHubAdapter
from starpulse.views.application.commands.guard import EDIT_LOCK, RELEASED_ASSIGNEE, held_task, not_held, with_request

lazy from starpulse.sessions.identity import same_session

logger = logging.getLogger(__name__)

#: The forge adapters by instance name: the one place a URL turns into a change reference and back.
type Forges = Mapping[str, GitHubAdapter]
type _Answer = tuple[int, dict[str, Any]]


def _text(ref: ChangeRef) -> str:
    return f"change:{ref.adapter}:{ref.id}"


def _change(ref: str, forges: Forges) -> ChangeRef | str:
    """The change `ref` names, or why it names none a configured forge owns."""
    kind, _, rest = ref.partition(":")
    instance, _, identity = rest.partition(":")
    if kind != "change":
        return f"{ref!r} is a {kind} reference, and only a change (a pull request) is linked"
    if (forge := forges.get(instance)) is None:
        return f"{ref!r} names the {instance!r} adapter, and the configured ones are {', '.join(forges)}"
    named = ChangeRef(adapter=instance, id=identity)
    try:
        forge.change_url(named)
    except ValueError as error:
        return str(error)
    return named


def _target(request: LinkPutRequest, forges: Forges) -> ChangeRef | _Answer:
    if request.ref is not None:
        named = _change(request.ref, forges)
        return named if isinstance(named, ChangeRef) else (400, {"error": named})
    assert request.url is not None
    reasons: list[str] = []
    for forge in forges.values():
        try:
            return forge.change_ref(request.url)
        except ValueError as error:
            reasons.append(str(error))
    return 400, {"error": "; ".join(reasons), "url": request.url, "adapters": list(forges)}


def _link(link: StoredLink, handle: str, forges: Forges) -> dict[str, Any]:
    _, _, rest = link.ref.partition(":")
    instance, _, identity = rest.partition(":")
    forge = forges.get(instance)
    return {
        "task": link.task,
        "handle": handle,
        "role": link.role,
        "ref": link.ref,
        "url": None if forge is None else forge.change_url(ChangeRef(adapter=instance, id=identity)),
        "requestedBy": link.requested_by,
        "at": datetime.fromtimestamp(link.at, UTC).isoformat(),
        "event": link.event,
    }


def _holding(feed: BoardFeed, handle: str, session: str, harness: str) -> _Answer | None:
    """The refusal of a session that does not hold `handle`, else None."""
    if (agent := held_task(feed, handle)) is None:
        return not_held(feed, handle)
    holder = str(agent.get("assignee") or "")
    if holder and holder != RELEASED_ASSIGNEE and same_session(holder, session):
        return None
    named = holder if holder and holder != RELEASED_ASSIGNEE else None
    return 403, {
        "error": f"{handle} is held by {named}, not by this session ({session}): only its holder links it"
        if named
        else f"{handle} is held by no session: only its holder links it",
        "session": f"session:{harness}:{session}",
        "holder": None if named is None else f"session:{harness}:{named}",
    }


class _Named(NamedTuple):
    uuid: str
    handle: str


def _task(tasks: ReadModel, token: str, read: TaskReader, store: EventStore) -> _Named | _Answer:
    """The UUID and handle of the task `token` names, or its 404 or 409. A task whose History lacks a UUID its file holds is
    stamped with the file's, so the read model carries it from then on."""
    if (found := tasks.task(token)) is None:
        return 404, {"error": f"{token} is not on the board"}
    handle = str(found["id"])
    if not (uuid := str((found.get("meta") or {}).get("uuid") or "")):
        if not (uuid := str((read(handle) or {}).get("uuid") or "")):
            return 409, {"error": f"{handle} has no UUID yet: a link is keyed by it"}
        stamp_task(store, handle, uuid)
    return _Named(uuid, handle)


@with_request(LinkPutRequest, "Linking a task")
def put_link(
    request: LinkPutRequest,
    token: str,
    feed: BoardFeed,
    tasks: ReadModel,
    links: TaskLinks,
    forges: Forges,
    read: TaskReader,
    store: EventStore,
    frozen: Callable[[str], None],
) -> _Answer:
    """`PUT /api/tasks/{id}/links`: 201 with the link written, 200 with the link already stored, else its refusal.
    A link written to a frozen task tells `frozen`, so the new pull request gets the freeze's check; a raise is logged."""
    if not isinstance(found := _task(tasks, token, read, store), _Named):
        return found
    uuid, handle = found
    if isinstance(target := _target(request, forges), tuple):
        return target
    ref, who = _text(target), f"session:{request.harness}:{request.session}"
    try:
        with EDIT_LOCK:
            if refused := _holding(feed, handle, request.session, request.harness):
                return refused
            link, written = links.put(uuid, request.role, ref, who)
    except DeliveredElsewhere as other:
        owner = tasks.task(other.task)
        return 409, {
            "error": f"{ref} already delivers another task",
            "ref": ref,
            "task": other.task,
            "handle": str(owner["id"]) if owner is not None else other.task,
        }
    except StaleVersion:
        return 409, {"error": f"{handle}'s links moved while this was written: send it again"}
    if written and (tasks.task(token) or {}).get("meta", {}).get("frozen"):
        try:
            frozen(handle)
        except Exception:
            logger.exception("the frozen hook for %s failed after its link %s was stored", handle, ref)
    return (201 if written else 200), _link(link, handle, forges)


@with_request(LinkDeleteRequest, "Removing a task's link")
def delete_link(
    request: LinkDeleteRequest, token: str, feed: BoardFeed, tasks: ReadModel, links: TaskLinks, forges: Forges, read: TaskReader, store: EventStore
) -> _Answer:
    """`DELETE /api/tasks/{id}/links`: 200 with the link as it was, else its refusal."""
    if not isinstance(found := _task(tasks, token, read, store), _Named):
        return found
    uuid, handle = found
    try:
        with EDIT_LOCK:
            if refused := _holding(feed, handle, request.session, request.harness):
                return refused
            link = links.remove(uuid, request.role, request.ref, f"session:{request.harness}:{request.session}")
    except StaleVersion:
        return 409, {"error": f"{handle}'s links moved while this was removed: send it again"}
    if link is None:
        return 404, {"error": f"{handle} has no {request.role} link to {request.ref}"}
    return 200, _link(link, handle, forges)
