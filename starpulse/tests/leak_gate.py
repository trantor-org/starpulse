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
from memray import FileReader, Tracker

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


def _window_bytes(step: Callable[[], None], iterations: int, capture: Path) -> int:
    """Net bytes allocated and not freed while `step` ran `iterations` times under one tracker."""
    with Tracker(str(capture)):
        for _ in range(iterations):
            step()
        gc.collect()
    with FileReader(str(capture)) as reader:
        return sum(record.size for record in reader.get_leaked_allocation_records(merge_threads=True))


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
    return retained


# Retained bytes after `iterations` runs of the context's loop, measured on CPython 3.14 and declared with headroom.
# A context that now holds more has leaked or grown: find the cause before raising its budget.
BUDGETS: dict[str, Budget] = {
    "pull-sync": Budget(iterations=200, retained_bytes=32 * 1024),
    "autopilot": Budget(iterations=200, retained_bytes=96 * 1024),
}
