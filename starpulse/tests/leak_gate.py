"""Memory budgets for the background contexts: each context's loop runs a fixed number of iterations under memray and
must end holding no more than its budget."""

from __future__ import annotations

import gc
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from memray import AllocationRecord, FileReader, Tracker

WARMUP_ITERATIONS = 5
WINDOWS = 2


#: A test measures only where memray sees allocations (the free-threaded build reports none) and owns the one Tracker
#: (`pytest --memray`, which ci/memray_flagged.py reruns slow tests under, holds it for the whole test).
measures_allocations = pytest.mark.skipif(
    not sys._is_gil_enabled() or any(arg.startswith("--memray") for arg in sys.argv),
    reason="memray reports no allocation on the free-threaded build, and only one Tracker may be active under --memray",
)


class LeakBudgetExceededError(AssertionError):
    """A context retained more memory over its workload than its budget allows."""


@dataclass(frozen=True)
class Budget:
    """`retained_bytes` a context may hold after `iterations` further runs of its step."""

    iterations: int
    retained_bytes: int


def _under_window(record: AllocationRecord) -> bool:
    """Whether `record` was allocated beneath `_window_bytes`, so on its thread rather than one another test left."""
    return any(function == "_window_bytes" and filename == __file__ for function, filename, _ in record.stack_trace())


def _window_bytes(step: Callable[[], None], iterations: int, capture: Path) -> int:
    """Net bytes `step` allocated and did not free while it ran `iterations` times under one tracker.

    The tracker sees every thread, and a daemon thread an earlier test in the process started keeps allocating, so
    only allocations beneath this frame count.
    """
    with Tracker(str(capture)):
        for _ in range(iterations):
            step()
        gc.collect()
    with FileReader(str(capture)) as reader:
        records = reader.get_leaked_allocation_records(merge_threads=False)
        return sum(record.size for record in records if _under_window(record))


def retained_bytes(step: Callable[[], None], iterations: int) -> int:
    """Net bytes `step` keeps per window of `iterations` runs, once its first runs have warmed caches.

    Two consecutive windows run and the lower counts: a leak holds memory in both, while a one-time allocation (a lazy
    cache, a database connection's page-cache slab) lands in one.
    """
    for _ in range(WARMUP_ITERATIONS):
        step()
    with tempfile.TemporaryDirectory() as scratch:
        captures = (Path(scratch) / f"window-{window}.bin" for window in range(WINDOWS))
        return min(_window_bytes(step, iterations, capture) for capture in captures)


def check(context: str, step: Callable[[], None], budget: Budget) -> int:
    """Run `step` under memray; raise `LeakBudgetExceededError` naming `context` when it retains over `budget`."""
    retained = retained_bytes(step, budget.iterations)
    if retained > budget.retained_bytes:
        message = (
            f"{context}: retained {retained} B over {budget.iterations} iterations, "
            f"budget {budget.retained_bytes} B exceeded"
        )
        raise LeakBudgetExceededError(message)
    return retained


# Retained bytes after `iterations` runs of the context's loop, measured on CPython 3.14 and declared with headroom.
# A context that now holds more has leaked or grown: find the cause before raising its budget.
BUDGETS: dict[str, Budget] = {
    "pull-sync": Budget(iterations=200, retained_bytes=32 * 1024),
    "autopilot": Budget(iterations=200, retained_bytes=96 * 1024),
}
