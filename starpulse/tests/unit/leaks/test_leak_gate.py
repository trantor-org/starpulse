"""The gate fails a context that keeps allocating and passes one that frees what it allocates."""

from __future__ import annotations


import pytest

from starpulse.tests.leak_gate import Budget, LeakBudgetExceededError, check, measures_allocations

pytestmark = measures_allocations

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
