"""Whether a task's assignee and a session are one session, whatever id each names it by: the harness adapter answers."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

from starpulse.sessions.harness import DEFAULT, configured
from starpulse.sessions.ports.identity import SessionIdentity

_identity: SessionIdentity | None = None


def current() -> SessionIdentity:
    """The default harness's identity, until `using` names another."""
    global _identity
    if _identity is None:
        _identity = configured(DEFAULT, os.environ).identity()
    return _identity


@contextmanager
def using(identity: SessionIdentity) -> Iterator[None]:
    global _identity
    previous, _identity = _identity, identity
    try:
        yield
    finally:
        _identity = previous


def same_session(held: str | None, wanted: str) -> bool:
    """Whether the assignee `held` and the session `wanted` name one session, in any of its ids."""
    if not held:
        return False
    return held == wanted or not current().aliases(held).isdisjoint(current().aliases(wanted))
