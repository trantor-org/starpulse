"""The lenses a task's latest qa round recorded a verdict for, read from the history store's machine events.

The store keeps a qa event by task and name alone, so the lens is the state the qa machine held the task in when the event
arrived: the ingest's own placement, replayed."""

from collections.abc import Callable, Iterable
from functools import cache
from pathlib import Path

from sqlalchemy import Engine, select

from starpulse.board.adapters.project_machines import DIRECTORY
from starpulse.event_log.readmodel import task_uuid
from starpulse.event_log.tables import machine_events
from starpulse.machine_engine.model.transitions import Table

__all__ = ["lenses_of", "verdict_lenses"]

MACHINE = "qa"
#: The events that record a lens's verdict; a skip or a timeout records none.
VERDICTS = frozenset({"LENS_PASSED", "LENS_UPHELD", "LENS_DISPUTED"})
OPENS = "ROUND_STARTED"


def verdict_lenses(table: Table, events: Iterable[str]) -> frozenset[str]:
    """The lenses the latest round of `events` (oldest first) recorded a verdict for.

    A round opens at `ROUND_STARTED`, or at an event arriving after a final state."""
    state: str | None = None
    lenses: set[str] = set()
    for event in events:
        if event == OPENS or state in table.finals:
            lenses.clear()
        source = table.initial if state is None or state in table.finals else state
        state = table.target(state, event) or state
        if event in VERDICTS:
            lenses.add(source.removesuffix("_dirty"))
    return frozenset(lenses)


def lenses_of(engine: Callable[[], Engine | None], base: Path) -> Callable[[str], frozenset[str]]:
    """A lookup of the lenses a task's latest qa round recorded a verdict for, empty when the board has no store or `base`
    declares no qa machine."""

    @cache
    def table() -> Table | None:
        from starpulse.machine_engine.adapters.machine_loader import (  # noqa: PLC0415 - import cost, paid on first use
            load_machine,
        )
        from starpulse.machine_engine.model.snapshot import describe  # noqa: PLC0415 - import cost, paid on first use

        path = base / DIRECTORY / f"{MACHINE}.yaml"
        return Table(describe(load_machine(path).machine)) if path.is_file() else None

    def read(task: str) -> frozenset[str]:
        held, bound = table(), engine()
        if held is None or bound is None:
            return frozenset()
        c = machine_events.c
        rows = select(c.event).where(c.task_uuid == task_uuid.of(task), c.machine == MACHINE).order_by(c.occurred_at, c.id)
        with bound.connect() as db:
            return verdict_lenses(held, [row.event for row in db.execute(rows)])

    return read
