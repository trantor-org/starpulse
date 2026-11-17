"""Whether an event subject's latest event already happened: the one the task actor reads when a task parks on it."""

from sqlalchemy import Engine, func, select

from starpulse.bridge.subjects import token
from starpulse.event_log.opening import last_machine_event
from starpulse.event_log.tables import machine_events

#: The entities whose runs index their events (`alert.<rule>`, `deploy.<component>`), so the latest one is a lookup.
LAST_READABLE = frozenset({"alert", "deploy"})


def readable(subject: str) -> bool:
    """Whether `subject` is `starpulse.<board>.<entity>.<id>.<event>` of an entity whose latest event can be read."""
    parts = subject.split(".")
    return len(parts) == 5 and parts[0] == "starpulse" and parts[2] in LAST_READABLE and all(parts)


def _stored_run(engine: Engine, entity: str, run: str) -> str:
    """The run `entity` recorded whose subject token is `run`, newest first; the events store the name untokenized."""
    c = machine_events.c
    newest = (
        select(c.run).where(c.machine == entity, c.run.is_not(None)).group_by(c.run).order_by(func.max(c.id).desc())
    )
    with engine.connect() as db:
        return next((name for name in db.execute(newest).scalars() if token(name) == run), run)


def last_event_is(engine: Engine, subject: str) -> bool:
    """Whether the latest event of `subject`'s run, as the bridge names it, is the subject's own."""
    if not readable(subject):
        return False
    _, _, entity, run, event = subject.split(".")
    last = last_machine_event(engine, entity, _stored_run(engine, entity, run))
    return last is not None and token(last.removeprefix("PR_").lower()) == event
