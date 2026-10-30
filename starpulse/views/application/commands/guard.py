"""The guards every write shares: who wrote it, whether its task is placed, a body parsed through its request model and the
refusal of a request another web page may have sent.

A write that names a task the feed has not placed waits up to `REPLAY_WAIT_S` for a replay in progress, then answers 503
with `Retry-After`, which a client sends again, never 404 for a task the replay has yet to reach. Every handler parses its
body through the request model it is declared with (`with_request`, `contracts.api.dto.requests`): a body that is not
JSON, not an object, or holds an unnamed key, a field of the wrong type or a blank `actor`, `session` or `harness` answers
400 `invalid request: <field>: <reason>` for its first fault, whatever the route's own "400 for" list names."""

from __future__ import annotations

import contextlib
import functools
import ipaddress
import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Concatenate, NamedTuple
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import (
    AGENT,
    ANONYMOUS,
    Written,
)
from starpulse.contracts.api.dto.requests import (
    _Writer,
)

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass

logger = logging.getLogger(__name__)


#: Who may press Run now, loopback and the RFC 1918 ranges as (octets, prefix): the page is never
#: exposed to the internet, so a LAN browser needs no token (the React/Vite ADR).
_LAN = (
    ipaddress.ip_network("::1"),
    *(
        ipaddress.ip_network((bytes(octets), prefix))
        for octets, prefix in (
            ((127, 0, 0, 0), 8),
            ((10, 0, 0, 0), 8),
            ((172, 16, 0, 0), 12),
            ((192, 168, 0, 0), 16),
        )
    ),
)


#: Saves hold this from reading a task's current record to writing, so two browsers saving one task cannot both pass the stale check.
EDIT_LOCK = threading.Lock()


#: How long a task write waits, in seconds, for a restarted instance's replay to place its task before it answers 503.
REPLAY_WAIT_S = 5.0
#: Seconds a client is asked, in `Retry-After`, to wait before it sends again a write answered 503.
RETRY_AFTER_S = 3


def held_task(feed: BoardFeed, task: str) -> dict | None:
    """The open task `task` as the feed holds it (a cold done task as its stub), waiting up to `REPLAY_WAIT_S` for a
    replay that has not placed it.

    A restarted instance serves before it has read its stream, when a task it holds is absent only because the replay
    has not reached it; the wait ends at the replay, and a feed that is not replaying answers at once.
    """
    if (agent := feed.held(task)) is None and feed.wait_replayed(REPLAY_WAIT_S):
        agent = feed.held(task)
    return agent


def is_held(feed: BoardFeed, task: str) -> bool:
    """Whether the feed holds the open task `task`, as `held_task` finds it but without building the moves it offers,
    which a read of the task's record does not use."""
    return feed.is_open(task) or (feed.wait_replayed(REPLAY_WAIT_S) and feed.is_open(task))


def not_held(feed: BoardFeed, task: str) -> tuple[int, dict[str, str]]:
    """The refusal for a task `held_task` did not find: 503, which a client sends again, while the replay has not ended,
    else 404."""
    if feed.wait_replayed(0):
        return 404, {"error": f"{task} is not on the board"}
    return 503, {"error": f"{task} is not on the board yet: the board is replaying its feed, retry"}


def on_lan(source: str) -> bool:
    return any(ipaddress.ip_address(source) in net for net in _LAN)


def lan_refusal(what: str) -> tuple[int, dict[str, str]]:
    """The 403 for `what` written from an address beyond the LAN."""
    return 403, {"error": f"{what} answers only loopback and private network (RFC 1918) browsers"}


def _invalid(error: ValidationError) -> tuple[int, dict[str, str]]:
    """The 400 for a body its request model refuses: the first fault, with the field it is in."""
    fault = error.errors()[0]
    where = ".".join(str(part) for part in fault["loc"])
    return 400, {"error": f"invalid request: {where + ': ' if where else ''}{fault['msg']}"}


type _Answer = tuple[int, Any]


def with_request[R: BaseModel, **P](
    model: type[R], what: str
) -> Callable[[Callable[Concatenate[R, P], _Answer]], Callable[Concatenate[str, bytes, P], _Answer]]:
    """Make a handler of a parsed `model` into a write route's: `what` is refused 403 from beyond the LAN, a body
    `model` refuses is the one 400 `_invalid` words, and the handler takes the parsed request in the body's place."""

    def decorate(handler: Callable[Concatenate[R, P], _Answer]) -> Callable[Concatenate[str, bytes, P], _Answer]:
        @functools.wraps(handler)
        def parsed(source: str, raw: bytes, *args: P.args, **kwargs: P.kwargs) -> _Answer:
            if not on_lan(source):
                return lan_refusal(what)
            try:
                request = model.model_validate_json(raw, strict=True)
            except ValidationError as error:
                return _invalid(error)
            return handler(request, *args, **kwargs)

        return parsed

    return decorate


def write_refusal(origin: str | None, host: str | None, content_type: str | None) -> tuple[int, dict[str, str]] | None:
    """The refusal of a write that may have been sent by another web page, or None when it may go on.

    A page the operator opens reaches this server from the operator's own address, so the source check alone lets it
    write. A browser names the page's origin on a cross-site write, so an `origin` that is not this server's own (`host`
    is the `Host` header it was sent to) is 403, and `null` with it. A write must also say it is JSON: a form or a
    `text/plain` post, the cross-site requests a browser sends without asking first, is 415. The CLI sends no origin.
    """
    if origin is not None and urlsplit(origin).netloc != host:
        return 403, {"error": "A write answers only a page this server served: its origin is not this server's"}
    if (content_type or "").partition(";")[0].strip().lower() != "application/json":
        return 415, {"error": "A write must be sent as Content-Type: application/json"}
    return None


class Who(NamedTuple):
    """Who makes a write: its actor, and the session and harness it names, each empty when it names none."""

    actor: str
    session: str
    harness: str

    @property
    def created_by(self) -> str:
        """What a create stamps in the task: `<harness>:<session>`, or `anonymous` when the write names no session."""
        return f"{self.harness}:{self.session}" if self.session and self.harness else self.session or ANONYMOUS


def who_of(request: _Writer) -> Who:
    """Who `request` names as its writer.

    A write that names no actor is an agent's when it names a session and anonymous when it names none: never the
    operator, whom only the page names.
    """
    session = (request.session or "").strip()
    return Who((request.actor or (AGENT if session else ANONYMOUS)).strip(), session, (request.harness or "").strip())


def record_written(feed: BoardFeed | None, task: str | None, who: Who, write: Callable[[], Written]) -> Written:
    """Run `write` of `task` (None: the task the write makes, named by its output) and, when it put the task in a lane,
    record that lane change with `who` as its actor, session and harness.

    The feed's placing is held from the write to the record, so the board's poll that places the change the moment the
    file lands finds it recorded and records nothing more: a write refused, or one that moves no lane, records nothing.
    """
    with feed.recording if feed is not None else contextlib.nullcontext():
        written = write()
        if feed is not None and written.ok and written.lane:
            feed.record_written(
                task or written.output,
                written.lane,
                written.at or time.time(),
                (who.actor, who.session, who.harness),
            )
    return written
