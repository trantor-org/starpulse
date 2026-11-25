"""Whether an event subject's latest event already happened, and since when: what the task actor reads on a park.

The log is read first, but only past the history recorder's cursor: the recorder copies an entry after it is appended
and a park in that gap would miss it, while every entry before the cursor is in the history, which also holds the
events the log has pruned."""

from sqlalchemy import Engine, func, select

from starpulse.bridge.subjects import token
from starpulse.event_log.checkpoints import Checkpoints
from starpulse.event_log.events import STREAM
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


def _logged(engine: Engine, entity: str, run: str) -> tuple[str, str | None, float] | None:
    """The newest event `entity` appended to the log, past the recorder's cursor, for the run whose subject token is
    `run`, with the build it named and its time; None when it holds none."""
    c = events.c
    copied = Checkpoints(engine).load(STREAM)[0] or 0
    newest = (
        select(c.fields)
        .where(c.stream == STREAM, c.id > copied, c.fields["machine"].as_string() == entity)
        .order_by(c.id.desc())
    )
    with engine.connect() as db:
        return next(
            (
                (f["event"], (f.get("data") or {}).get("sha"), float(f["time"]))
                for f in db.execute(newest).scalars()
                if f.get("run") is not None and token(f["run"]) == run
            ),
            None,
        )


def _stored(engine: Engine, entity: str, run: str) -> tuple[str, str | None, float] | None:
    c = machine_events.c
    newest = select(c.event, c.sha, c.occurred_at).where(c.machine == entity, c.run == run).order_by(c.id.desc()).limit(1)
    with engine.connect() as db:
        row = db.execute(newest).first()
    return (row.event, row.sha, row.occurred_at) if row else None


def _last(engine: Engine, subject: str, since: float) -> tuple[str | None, str | None]:
    """The event and build of the latest event of `subject`'s run when it is the subject's own and was recorded at or
    after `since` (epoch seconds), else `(None, None)`."""
    if not readable(subject):
        return None, None
    _, _, entity, run, event = subject.split(".")
    last = _logged(engine, entity, run) or _stored(engine, entity, _stored_run(engine, entity, run))
    if last is None or last[2] < since or token(last[0].removeprefix("PR_").lower()) != event:
        return None, None
    return last[0], last[1]


def last_event_is(engine: Engine, subject: str, since: float = 0.0) -> bool:
    """Whether the latest event of `subject`'s run, as the bridge names it, is the subject's own and was recorded at or
    after `since` (epoch seconds)."""
    return _last(engine, subject, since)[0] is not None


def last_event_sha(engine: Engine, subject: str) -> str | None:
    """The build the latest event of `subject`'s run named, when that event is the subject's own; None when it is
    not, or named none (an event recorded before the column existed)."""
    return _last(engine, subject, 0.0)[1]
