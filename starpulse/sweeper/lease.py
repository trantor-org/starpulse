"""The sweeper's lease: a row of `starpulse_leases` that one process holds, taken over only from a dead holder."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from starpulse.event_log.tables import leases


class LeaseHeld(RuntimeError):
    """The lease is held by a live process; the message names it."""


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True)
class Lease:
    engine: Engine
    name: str
    pid: int

    def release(self) -> None:
        """Give the lease up; a lease another process took over since is left as it is."""
        with self.engine.begin() as db:
            db.execute(delete(leases).where(leases.c.name == self.name, leases.c.holder == self.pid))


def acquire(
    engine: Engine, name: str, *, pid: int | None = None, alive: Callable[[int], bool] = process_alive
) -> Lease:
    """Take the lease `name` for `pid` (this process). Raises `LeaseHeld` naming the holder while its process is alive;
    the row of a holder whose process is gone is taken over by a compare-and-swap, so two takers never both win."""
    pid = os.getpid() if pid is None else pid
    with engine.begin() as db:
        try:
            with db.begin_nested():
                db.execute(insert(leases).values(name=name, holder=pid, taken_at=time.time()))
        except IntegrityError:
            held = db.execute(select(leases.c.holder).where(leases.c.name == name)).scalar()
            if held is not None and alive(held):
                raise LeaseHeld(f"the {name} lease is held by pid {held}") from None
            swapped = db.execute(
                update(leases)
                .where(leases.c.name == name, leases.c.holder == held)
                .values(holder=pid, taken_at=time.time())
            )
            if swapped.rowcount != 1:
                raise LeaseHeld(f"the {name} lease was taken by another process") from None
    return Lease(engine, name, pid)
