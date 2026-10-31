"""A board of 20,000 Tasks with 18,000 archived: every read-model query stays inside the page budget and the memory
soft limit, and the shape the read model replaces (load every Task, filter in Python) does not."""

import os
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
# The two snapshot reads build every live card with its Acceptance Criteria: ~2,000 cards and ~4,000 criteria
# rows turned into dicts, ~35-70 CPU-ms at best on a loaded ai-vm-1, 2.5x the cards-only read that 50 ms was set for. The board
# feed caches them by read-model position, so a page request pays this only after a change.
_SNAPSHOT_BUDGET_MS = 100.0
_SNAPSHOT_SURFACES = ("snapshot", "snapshot by state")
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


def _floor_ms(call: Callable[[], object], budget_ms: float) -> float:
    """The fastest of up to `_RUNS` calls by the thread's own CPU time, stopping at the first one inside `budget_ms`: a
    minimum only falls, so that call already settles the verdict, and the snapshot reads (~65 CPU-ms) would otherwise
    spend 33 calls proving it. ai-vm-1 runs the nightly's workers at a load average of 100+, so a wall clock bills the
    call for its wait in the run queue (snapshot: 195-674 ms for ~65 CPU-ms) and even the p95 of CPU time inflates 3x from
    hyperthread and cache contention; the fastest call is the cost the code adds."""
    floor = float("inf")
    for _ in range(_RUNS):
        started = time.thread_time()
        call()
        floor = min(floor, (time.thread_time() - started) * 1000)
        if floor <= budget_ms:
            break
    return floor


def _budget_ms(name: str) -> float:
    return _SNAPSHOT_BUDGET_MS if name in _SNAPSHOT_SURFACES else _BUDGET_MS


# Slow: the first run after an event-log source change seeds 20,000 Tasks through the real `EventStore` and `Projector`
# (~3 CPU-ms a Task, nearly all SQLAlchemy statement building); later runs copy the cached store. The setup is billed to
# the first test that asks for the board; the three tests' own calls cost ~6 s, ~1.5 s of it this test's.
@pytest.fixture(scope="module")
def board(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[ReadModel, int, int]]:
    rss_before = _rss()
    model = seeded_server.seed_read_model(tmp_path_factory.mktemp("board"), _TOTAL, _ARCHIVED)
    yield model, rss_before, model.since(0, _TOTAL)[-500]["seq"]


def _load_per_cpu() -> float:
    return os.getloadavg()[0] / (os.cpu_count() or 1)


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


# Slow: whichever test runs first seeds 20,000 Tasks through the real write path, ~55 s CPU on a seed-cache miss, ~1 s warm.
def test_every_query_is_within_the_page_budget_on_twenty_thousand_tasks_with_eighteen_thousand_archived(board) -> None:
    model, _, cursor = board
    floor = {name: _floor_ms(call, _budget_ms(name)) for name, call in _surfaces(model, cursor).items()}

    over = {name: ms for name, ms in floor.items() if ms > _budget_ms(name)}
    assert over == {}, seeded_server.budget_message(floor, _load_per_cpu())


# Slow: whichever test runs first seeds 20,000 Tasks through the real write path, ~55 s CPU on a seed-cache miss, ~1 s warm.
def test_the_board_context_stays_under_its_memory_soft_limit_after_every_query(board) -> None:
    model, rss_before, cursor = board
    for call in _surfaces(model, cursor).values():
        for _ in range(_RUNS):
            call()

    assert _rss() - rss_before < _RSS_SOFT_LIMIT


# Slow: whichever test runs first seeds 20,000 Tasks through the real write path, ~55 s CPU on a seed-cache miss, ~1 s warm.
def test_loading_every_task_to_filter_in_python_is_over_the_budget_so_this_run_can_fail(board) -> None:
    model, _, _ = board

    def load_everything_and_filter() -> list[dict]:
        return [item for item in model.since(0, _TOTAL) if not item["archived"]]

    assert len(load_everything_and_filter()) == _TOTAL - _ARCHIVED
    # One load costs ~5x the budget: the fastest of three is enough, where the floors above re-ran it 30 times.
    assert min(_timed_ms(load_everything_and_filter) for _ in range(3)) > _BUDGET_MS
