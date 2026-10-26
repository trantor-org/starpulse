"""The gate fails a context that keeps allocating and passes one that frees what it allocates."""

from __future__ import annotations

import threading
import time

import pytest

from tests.leak_gate import Budget, LeakBudgetExceededError, check, measures_allocations

# Budget tests run in the nightly only: they measure a workload, so they cannot fit the gate's 5 s ceiling.
pytestmark = [measures_allocations, pytest.mark.nightly]

LEAKED: list[bytearray] = []
BUDGET = Budget(iterations=200, retained_bytes=50_000)


def _leak() -> None:
    LEAKED.append(bytearray(1024))


def _tidy() -> None:
    scratch = [bytearray(1024) for _ in range(8)]
    assert len(scratch) == 8


def test_a_context_that_retains_memory_every_iteration_exceeds_its_budget_and_is_named() -> None:
    with pytest.raises(LeakBudgetExceededError, match=r"leaky-context.*budget"):
        check("leaky-context", _leak, BUDGET)


def test_a_context_that_frees_what_it_allocates_stays_within_its_budget() -> None:
    check("tidy-context", _tidy, BUDGET)


def test_a_thread_another_test_left_running_does_not_count_against_the_context() -> None:
    held: list[bytearray] = []
    done = threading.Event()

    def stray() -> None:
        while not done.is_set():
            held[:] = [bytearray(BUDGET.retained_bytes + 1)]
            time.sleep(0)

    thread = threading.Thread(target=stray, name="stray", daemon=True)
    thread.start()
    try:
        check("tidy-context", _tidy, BUDGET)
    finally:
        done.set()
        thread.join()
