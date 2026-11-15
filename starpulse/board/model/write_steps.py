"""The steps of one board write, timed so a slow write logs which step held the time.

A write route times its write with `timed`; the board code it runs marks the end of each step with `step`, a no-op
outside a timed write. A write that took `SLOW_WRITE_S` or more logs one `slow_write` line with the seconds of each
step, from its arrival: `queue` (waiting for a worker thread), then each step marked, then `answer` (encoding it).
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

logger = logging.getLogger(__name__)

#: A write that takes this many seconds or more, from its arrival to its answer, logs its `slow_write` line.
SLOW_WRITE_S = 5.0

_STEPS: ContextVar[list[tuple[str, float]] | None] = ContextVar("write_steps", default=None)


def step(name: str) -> None:
    """Mark the end of the step `name` of the write running in this context, if one is timed."""
    if (steps := _STEPS.get()) is not None:
        steps.append((name, time.monotonic()))


@contextmanager
def timing() -> Iterator[list[tuple[str, float]]]:
    """The steps marked inside the block, each as its name and the monotonic time it ended."""
    steps: list[tuple[str, float]] = []
    token = _STEPS.set(steps)
    try:
        yield steps
    finally:
        _STEPS.reset(token)


@contextmanager
def timed(route: str, arrived: float) -> Iterator[None]:
    """Time the write to `route` that arrived at the monotonic time `arrived`, logging it when it is slow."""
    with timing() as steps:
        step("queue")
        try:
            yield
        finally:
            step("answer")
            total = steps[-1][1] - arrived
            if total >= SLOW_WRITE_S:
                starts = [arrived, *(at for _, at in steps)]
                spent = " ".join(f"{name}_s={at - start:.3f}" for (name, at), start in zip(steps, starts, strict=False))
                logger.warning("slow_write route=%s total_s=%.3f %s", route, total, spent)
