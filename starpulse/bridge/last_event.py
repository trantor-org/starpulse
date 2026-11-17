"""Whether an event subject's latest event already happened: the one the task actor reads when a task parks on it."""

from sqlalchemy import Engine

from starpulse.bridge.subjects import token
from starpulse.event_log.opening import last_machine_event

#: The entities whose runs index their events (`alert.<rule>`, `deploy.<component>`), so the latest one is a lookup.
LAST_READABLE = frozenset({"alert", "deploy"})


def readable(subject: str) -> bool:
    """Whether `subject` is `starpulse.<board>.<entity>.<id>.<event>` of an entity whose latest event can be read."""
    parts = subject.split(".")
    return len(parts) == 5 and parts[0] == "starpulse" and parts[2] in LAST_READABLE and all(parts)


def last_event_is(engine: Engine, subject: str) -> bool:
    """Whether the latest event of `subject`'s run, as the bridge names it, is the subject's own."""
    if not readable(subject):
        return False
    _, _, entity, run, event = subject.split(".")
    last = last_machine_event(engine, entity, run)
    return last is not None and token(last.removeprefix("PR_").lower()) == event
