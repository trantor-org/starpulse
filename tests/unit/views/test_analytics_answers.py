"""`Answers`: the telemetry analytics answers kept in `starpulse_answers`, so a read never waits on the fold of the window."""

import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select

from starpulse.event_log.tables import analytics_answers, metadata
from starpulse.views.application.queries.answers import Answers


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'answers.sqlite'}")
    metadata.create_all(engine, tables=[analytics_answers])
    yield engine
    engine.dispose()


def _saved(engine: Engine) -> list[tuple[str, str, bytes, int]]:
    columns = (analytics_answers.c.view, analytics_answers.c.query, analytics_answers.c.body, analytics_answers.c.status)
    with engine.connect() as db:
        return [tuple(row) for row in db.execute(select(*columns).order_by(analytics_answers.c.query)).all()]


def _folds() -> tuple[list[int], Callable[[], tuple[bytes, int]]]:
    runs: list[int] = []

    def compute() -> tuple[bytes, int]:
        runs.append(1)
        return f"fold {len(runs)}".encode(), 200

    return runs, compute


def test_a_read_with_no_answer_folds_once_and_a_fresh_read_reuses_it(engine: Engine, clock: Clock) -> None:
    runs, compute = _folds()
    answers = Answers(engine, clock=clock)

    first = answers.answer("cells", "q", compute)
    second = answers.answer("cells", "q", compute)

    assert (first, second, len(runs)) == ((b"fold 1", 200), (b"fold 1", 200), 1)


def test_a_stale_read_answers_at_once_and_the_next_has_the_refolded_answer(engine: Engine, clock: Clock) -> None:
    runs, compute = _folds()
    answers = Answers(engine, clock=clock)
    answers.answer("cells", "q", compute)
    clock.now += 301

    stale = answers.answer("cells", "q", compute)
    answers.join()
    refolded = answers.answer("cells", "q", compute)

    assert (stale, refolded, len(runs)) == ((b"fold 1", 200), (b"fold 2", 200), 2)


def test_a_restart_serves_the_row_saved_before_any_fold_and_holds_no_body(engine: Engine, clock: Clock) -> None:
    _, compute = _folds()
    first = Answers(engine, clock=clock)
    first.answer("cells", "q", compute)
    first.join()
    runs, restart_compute = _folds()

    restarted = Answers(engine, clock=clock)
    after = restarted.answer("cells", "q", restart_compute)

    assert (after, len(runs), "_held" in vars(restarted)) == ((b"fold 1", 200), 0, False)


def test_readers_of_one_missing_answer_share_one_fold(engine: Engine, clock: Clock) -> None:
    entered, gate = threading.Event(), threading.Event()
    runs: list[int] = []

    def compute() -> tuple[bytes, int]:
        runs.append(1)
        entered.set()
        gate.wait(5)
        return b"one", 200

    answers = Answers(engine, clock=clock)
    results: list[tuple[bytes, int]] = []
    readers = [
        threading.Thread(target=lambda: results.append(answers.answer("cells", "q", compute))) for _ in range(4)
    ]
    for reader in readers:
        reader.start()
    entered.wait(5)
    gate.set()
    for reader in readers:
        reader.join(5)

    assert (results, len(runs)) == ([(b"one", 200)] * 4, 1)


def test_a_reader_whose_read_missed_the_row_a_fold_just_saved_does_not_fold_again(
    engine: Engine, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs: list[int] = []

    def compute() -> tuple[bytes, int]:
        runs.append(1)
        return b"one", 200

    answers = Answers(engine, clock=clock)
    answers.answer("cells", "q", compute)
    read, reads = answers._read, []

    def read_once_stale(key: tuple[str, str]) -> object:
        reads.append(1)
        return None if len(reads) == 1 else read(key)  # the first read predates the save

    monkeypatch.setattr(answers, "_read", read_once_stale)

    assert (answers.answer("cells", "q", compute), len(runs)) == ((b"one", 200), 1)


def test_a_refusal_is_returned_but_never_kept(engine: Engine, clock: Clock) -> None:
    runs: list[int] = []

    def refuse() -> tuple[bytes, int]:
        runs.append(1)
        return b"bad window", 400

    answers = Answers(engine, clock=clock)
    first = answers.answer("cells", "q", refuse)
    second = answers.answer("cells", "q", refuse)

    assert (first, second, len(runs), _saved(engine)) == ((b"bad window", 400),) * 2 + (2, [])


def test_a_failed_refold_keeps_the_stale_answer_and_waits_a_period_before_the_next(engine: Engine, clock: Clock) -> None:
    calls: list[int] = []

    def compute() -> tuple[bytes, int]:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("the window could not be read")
        return f"fold {len(calls)}".encode(), 200

    answers = Answers(engine, clock=clock)
    first = answers.answer("cells", "q", compute)
    clock.now += 301
    failed = answers.answer("cells", "q", compute)
    answers.join()
    clock.now += 1
    waiting = answers.answer("cells", "q", compute)
    waited = len(calls)
    clock.now += 300
    refolding = answers.answer("cells", "q", compute)
    answers.join()

    assert (first, failed, waiting, waited, refolding, len(calls)) == (
        (b"fold 1", 200),
        (b"fold 1", 200),
        (b"fold 1", 200),
        2,
        (b"fold 1", 200),
        3,
    )


def test_only_the_newest_kept_answers_are_saved(engine: Engine, clock: Clock) -> None:
    _, compute = _folds()
    answers = Answers(engine, clock=clock, kept=2)
    for query in ("a", "b", "c"):
        clock.now += 1
        answers.answer("cells", query, compute)
        answers.join()

    assert [query for _, query, _, _ in _saved(engine)] == ["b", "c"]


def test_folds_of_different_queries_run_one_at_a_time(engine: Engine, clock: Clock) -> None:
    """Each fold of a 168 h window holds its signals' rows as Python data; several at once multiplied the worker's peak
    (TASK-10788)."""
    answers = Answers(engine, clock=clock)
    first_in, release_first, second_in = threading.Event(), threading.Event(), threading.Event()

    def first() -> tuple[bytes, int]:
        first_in.set()
        release_first.wait(10)
        return b"first", 200

    def second() -> tuple[bytes, int]:
        second_in.set()
        return b"second", 200

    readers = [
        threading.Thread(target=answers.answer, args=("steps", "168", first)),
        threading.Thread(target=answers.answer, args=("steps", "48", second)),
    ]
    readers[0].start()
    assert first_in.wait(10)
    readers[1].start()

    overlapped = second_in.wait(0.5)
    release_first.set()
    for reader in readers:
        reader.join(10)

    assert not overlapped
    assert second_in.is_set()
