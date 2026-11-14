"""Whether `serve` can serve the board, as `GET /api/ready` and `starpulse rehearse` read it.

A server is ready when the event log is at the schema head, the Board is assembled, the Board context (the writer of
the Start Criteria dating) has started and every other supervised context has started. Each context records its start
in the `ready` worker state under the boot token `serve` handed it (`hold.BOOT_ENV`), so a stamp an earlier `serve` left in
the store, or one a rehearsal copied from the live store, never counts. A `serve` that re-executes and adopts a
child the old image started keeps that child's token; it drops the old image's stamps (`forget_starts`) unless it adopts
the `contexts` child, whose stamps stay true, so the Page API child counts the contexts the new image starts. A server started without `serve` has no token and checks no context.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

from starpulse.event_log.migrate import StoreNotMigrated, require_migrated

if TYPE_CHECKING:
    from starpulse.board.board_feed import BoardFeed
    from starpulse.event_log.event_log import EventLog

#: The worker state holding, by context, the boot token of the `serve` that started it.
READY_STATE = "ready"


def forget_starts(url: str) -> None:
    """Drop every context's stamp in the store at `url`: a `serve` that keeps its boot token across a re-exec
    (`hold.boot_token`) counts only the contexts its new image starts. Raises on a database error."""
    from sqlalchemy import create_engine, update  # noqa: PLC0415 - `serve` calls it before the database stack loads

    from starpulse.event_log.tables import worker_state  # noqa: PLC0415

    engine = create_engine(url)
    try:
        with engine.begin() as db:
            db.execute(update(worker_state).where(worker_state.c.name == READY_STATE).values(state={}))
    finally:
        engine.dispose()


#: The context whose process is the one writer of the Board's dating; `/api/ready` names it apart from the others.
WRITER = "board"


def stamp(log: EventLog, context: str, boot: str) -> None:
    """Record that `context` started in the boot `boot`."""
    log.put_state_entry(READY_STATE, context, boot)


def _part(ready: bool, detail: str) -> dict[str, Any]:
    return {"ready": ready, "detail": detail}


def _store(log: EventLog) -> dict[str, Any]:
    try:
        require_migrated(log.engine)
    except StoreNotMigrated as exc:
        return _part(False, str(exc))
    return _part(True, "at the schema head")


def _started(log: EventLog, expected: Sequence[str], boot: str | None) -> list[str]:
    """The contexts of `expected` that did not stamp `boot`."""
    try:
        _, kept = log.state(READY_STATE)
    except SQLAlchemyError:  # no `worker_state` table: the store component names why
        kept = None
    stamps = kept if isinstance(kept, dict) else {}
    return [context for context in expected if stamps.get(context) != boot]


def readiness(
    log: EventLog, feed: BoardFeed, contexts: Sequence[str], boot: str | None
) -> Callable[[], dict[str, Any]]:
    """The reader of the report `{ready, components}`, each component `{ready, detail}`; it reads, never writes.

    `contexts` is every context `serve` supervises, `boot` the token they stamp, or `None` when no `serve` started this
    process."""

    def report() -> dict[str, Any]:
        if boot is None:
            writer = contexts_part = _part(True, "not supervised")
        else:
            missing = _started(log, contexts, boot)
            writer = (
                _part(False, "not started")
                if WRITER in missing
                else _part(True, "started" if WRITER in contexts else "not run here")
            )
            others = [context for context in missing if context != WRITER]
            contexts_part = _part(False, f"not started: {', '.join(others)}") if others else _part(True, "all started")
        components = {
            "store": _store(log),
            "board": _part(feed.ready.is_set(), "assembled" if feed.ready.is_set() else "not assembled"),
            "writer": writer,
            "contexts": contexts_part,
        }
        return {"ready": all(part["ready"] for part in components.values()), "components": components}

    return report
