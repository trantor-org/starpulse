"""A board of 20,000 Tasks with 18,000 archived: every read-model query stays inside the page budget and the memory
soft limit, and the shape the read model replaces (load every Task, filter in Python) does not."""

import statistics
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.declared import declared_fields, ensure_columns
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore, NewEvent

pytestmark = [pytest.mark.nightly, pytest.mark.slow]

_TOTAL = 20_000
_ARCHIVED = 18_000
_BUDGET_MS = 50.0  # the page latency budget: bench/page_latency.py BUDGET_MS
_RSS_SOFT_LIMIT = 256 * 1024 * 1024  # growth the board context may add over a seeded board and every query below
_RUNS = 30
_DECLARED = declared_fields({"fields": {"area": {"type": "string", "queried": True}}})
_STATES = ("Ready", "In Progress", "Review")


def _rss() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    raise AssertionError("no VmRSS")


def _new(type: str, **payload: object) -> NewEvent:
    return NewEvent(type=type, payload=payload, actor="adin", writer="operator")


def _seed(store: EventStore) -> None:
    for number in range(1, _TOTAL + 1):
        archived = number <= _ARCHIVED
        events = [
            _new(
                "TaskCreated",
                title=f"Task {number} does a piece of the work",
                description="A paragraph of the kind of text a Task carries. " * 6,
                state="Done" if archived else _STATES[number % len(_STATES)],
                labels=["kind-execute", "size-3"],
                dependencies=[f"TASK-{number - 1}"] if number % 10 == 0 else [],
                fields={"area": f"area-{number % 20}"},
            )
        ]
        if archived:
            events.append(_new("Archived"))
        else:
            events += [_new("CriterionAdded", kind="ac", text=f"criterion {n}") for n in range(2)]
        store.append("task", f"TASK-{number}", 0, events)


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
def board() -> Iterator[tuple[ReadModel, int, int]]:
    rss_before = _rss()
    with tempfile.TemporaryDirectory() as directory:
        engine = EventLog(f"sqlite:///{Path(directory) / 'events.sqlite'}").engine
        ensure_columns(engine, _DECLARED)
        store = EventStore(engine)
        _seed(store)
        Projector(engine, store).catch_up()
        model = ReadModel(engine, _DECLARED)
        yield model, rss_before, model.since(0, _TOTAL)[-500]["seq"]
        engine.dispose()


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


# Slow: the module `board` fixture seeds and projects 20,000 Tasks through the real store (~3 ms each, SQLAlchemy and SQLite
# bound), and the first test to use it pays that; the scale is what the page budget is measured at, so it cannot shrink.
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
    assert _p95_ms(load_everything_and_filter) > _BUDGET_MS
