"""A board of 20,000 Tasks with 18,000 archived: every read-model query stays inside the page budget and the memory
soft limit, and the shape the read model replaces (load every Task, filter in Python) does not."""

import statistics
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import seeded_server

from starpulse.event_log.readmodel.read_model import ReadModel

pytestmark = [pytest.mark.nightly, pytest.mark.slow]

_TOTAL = 20_000
_ARCHIVED = 18_000
_BUDGET_MS = 50.0  # the page latency budget: bench/page_latency.py BUDGET_MS
_RSS_SOFT_LIMIT = 256 * 1024 * 1024  # growth the board context may add over a seeded board and every query below
_RUNS = 30


def _rss() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    raise AssertionError("no VmRSS")


def _timed_ms(call: Callable[[], object]) -> float:
    started = time.perf_counter()
    call()
    return (time.perf_counter() - started) * 1000


def _round_p95_ms(call: Callable[[], object]) -> float:
    samples = []
    for _ in range(_RUNS):
        started = time.perf_counter()
        call()
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.quantiles(samples, n=20)[-1]


def _p95_ms(call: Callable[[], object]) -> float:
    """The lowest p95 of three rounds: the host is shared, and a load spike inflates one round, never all three."""
    for _ in range(3):
        call()
    return min(_round_p95_ms(call) for _ in range(3))


@pytest.fixture(scope="module")
def board(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[ReadModel, int, int]]:
    rss_before = _rss()
    model = seeded_server.seed_read_model(tmp_path_factory.mktemp("board"), _TOTAL, _ARCHIVED)
    yield model, rss_before, model.since(0, _TOTAL)[-500]["seq"]


def _surfaces(model: ReadModel, cursor: int) -> dict[str, Callable[[], object]]:
    return {
        "snapshot": model.snapshot,
        "snapshot by state": lambda: model.snapshot("Ready"),
        "task, live": lambda: model.task(f"TASK-{_TOTAL}"),
        "task, archived": lambda: model.task("TASK-17"),
        "by declared field": lambda: model.with_field("area", "area-3"),
        "scheduler ready set": lambda: model.ready("Ready", "Done"),
        "delta since the cursor": lambda: model.since(cursor),
    }


def test_every_query_is_within_the_page_budget_on_twenty_thousand_tasks_with_eighteen_thousand_archived(board) -> None:
    model, _, cursor = board
    p95 = {name: _p95_ms(call) for name, call in _surfaces(model, cursor).items()}

    assert {name: ms for name, ms in p95.items() if ms > _BUDGET_MS} == {}, p95


def test_the_board_context_stays_under_its_memory_soft_limit_after_every_query(board) -> None:
    model, rss_before, cursor = board
    for call in _surfaces(model, cursor).values():
        for _ in range(_RUNS):
            call()

    assert _rss() - rss_before < _RSS_SOFT_LIMIT


def test_loading_every_task_to_filter_in_python_is_over_the_budget_so_this_run_can_fail(board) -> None:
    model, _, _ = board

    def load_everything_and_filter() -> list[dict]:
        return [item for item in model.since(0, _TOTAL) if not item["archived"]]

    assert len(load_everything_and_filter()) == _TOTAL - _ARCHIVED
    # One load costs ~5x the budget: the fastest of three is enough, where the p95 rounds above re-ran it ~100 times.
    assert min(_timed_ms(load_everything_and_filter) for _ in range(3)) > _BUDGET_MS
