"""Whether an event subject's latest event already happened: the one the task actor reads when a task parks on it.

The log is read first, but only past the history recorder's cursor: the recorder copies an entry after it is appended
and a park in that gap would miss it, while every entry before the cursor is in the history, which also holds the
events the log has pruned."""

from sqlalchemy import Engine, func, select

from starpulse.bridge.subjects import token
from starpulse.event_log.checkpoints import Checkpoints
from starpulse.event_log.events import STREAM
from starpulse.event_log.opening import last_machine_event
from starpulse.event_log.tables import events, machine_events

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


def _logged(engine: Engine, entity: str, run: str) -> str | None:
    """The newest event `entity` appended to the log, past the recorder's cursor, for the run whose subject token is
    `run`; None when it holds none."""
    c = events.c
    copied = Checkpoints(engine).load(STREAM)[0] or 0
    newest = (
        select(c.fields)
        .where(c.stream == STREAM, c.id > copied, c.fields["machine"].as_string() == entity)
        .order_by(c.id.desc())
    )
    with engine.connect() as db:
        return next((f["event"] for f in db.execute(newest).scalars() if f.get("run") is not None and token(f["run"]) == run), None)


def last_event_is(engine: Engine, subject: str) -> bool:
    """Whether the latest event of `subject`'s run, as the bridge names it, is the subject's own."""
    if not readable(subject):
        return False
    _, _, entity, run, event = subject.split(".")
    last = _logged(engine, entity, run) or last_machine_event(engine, entity, _stored_run(engine, entity, run))
    return last is not None and token(last.removeprefix("PR_").lower()) == event
