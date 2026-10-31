"""`Answers`: the telemetry analytics answers kept past a restart, so a read never waits on the fold of the window."""

import threading
from typing import Any

from pydantic import BaseModel
from starpulse.views.application.queries.answers import Answers


class Store:
    """The checkpoints the answers are saved in, as one dict."""

    def __init__(self) -> None:
        self.saved: dict[str, BaseModel] = {}

    def load(self, name: str, model: type[BaseModel] | None = None) -> tuple[int | None, BaseModel | None]:
        return (0, self.saved[name]) if name in self.saved else (None, None)

    def save(self, name: str, position: int, model: BaseModel | None = None, **_: Any) -> None:
        assert model is not None
        self.saved[name] = model


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Compute:
    """A fold that answers `body` and counts its runs."""

    def __init__(self, body: bytes = b"one", status: int = 200) -> None:
        self.body, self.status, self.runs = body, status, 0

    def __call__(self) -> tuple[bytes, int]:
        self.runs += 1
        return self.body, self.status


def _answers(store: Store, clock: Clock, kept: int = 8) -> Answers:
    return Answers(store, fresh_s=300.0, kept=kept, clock=clock)


def test_a_read_with_no_answer_folds_once_and_a_fresh_read_reuses_it() -> None:
    clock, compute = Clock(), Compute()
    answers = _answers(Store(), clock)

    first = answers.answer("cells?hours=168", compute)
    clock.now += 299
    second = answers.answer("cells?hours=168", compute)

    assert (first, second, compute.runs) == ((b"one", 200), (b"one", 200), 1)


def test_a_stale_read_answers_at_once_and_the_next_has_the_refolded_answer() -> None:
    clock, compute, store = Clock(), Compute(), Store()
    answers = _answers(store, clock)
    answers.answer("cells", compute)
    clock.now += 301
    compute.body = b"two"

    stale = answers.answer("cells", compute)
    answers.join()
    fresh = answers.answer("cells", compute)

    assert (stale, fresh, compute.runs) == ((b"one", 200), (b"two", 200), 2)


def test_a_restart_answers_from_the_saved_answer_before_any_fold() -> None:
    store, clock = Store(), Clock()
    _answers(store, clock).answer("cells", Compute(b"saved"))
    clock.now += 3600
    compute = Compute(b"new")

    restarted = _answers(store, clock)
    cold = restarted.answer("cells", compute)
    restarted.join()

    assert (cold, restarted.answer("cells", compute)) == ((b"saved", 200), (b"new", 200))


def test_readers_of_one_missing_answer_share_one_fold() -> None:
    release, started = threading.Event(), threading.Event()
    runs: list[int] = []

    def slow() -> tuple[bytes, int]:
        runs.append(1)
        started.set()
        release.wait(5)
        return b"one", 200

    answers = _answers(Store(), Clock())
    results: list[tuple[bytes, int]] = []
    readers = [threading.Thread(target=lambda: results.append(answers.answer("cells", slow))) for _ in range(3)]
    readers[0].start()
    started.wait(5)
    for reader in readers[1:]:
        reader.start()
    release.set()
    for reader in readers:
        reader.join(5)

    assert (results, len(runs)) == ([(b"one", 200)] * 3, 1)


def test_a_refusal_is_returned_but_never_kept() -> None:
    clock, refused = Clock(), Compute(b"too long", 400)
    answers = _answers(Store(), clock)

    first = answers.answer("cells", refused)
    second = answers.answer("cells", refused)

    assert (first, second, refused.runs) == ((b"too long", 400), (b"too long", 400), 2)


def test_a_refold_that_fails_keeps_the_stale_answer_and_waits_a_period_to_try_again() -> None:
    clock, compute = Clock(), Compute()
    answers = _answers(Store(), clock)
    answers.answer("cells", compute)
    clock.now += 301
    compute.body, compute.status = b"down", 503

    first = answers.answer("cells", compute)
    answers.join()
    second = answers.answer("cells", compute)
    answers.join()

    assert (first, second, compute.runs) == ((b"one", 200), (b"one", 200), 2)


def test_only_the_newest_answers_up_to_the_cap_are_kept() -> None:
    clock, store = Clock(), Store()
    answers = _answers(store, clock, kept=2)
    for key in ("a", "b", "c"):
        clock.now += 1
        answers.answer(key, Compute(key.encode()))

    restarted = _answers(store, clock)
    compute = Compute(b"folded")

    assert [restarted.answer(key, compute)[0] for key in ("b", "c", "a")] == [b"b", b"c", b"folded"]
