"""`run_contexts` runs every named context as a thread of one process, restarts one whose start raises while the
others' threads stay, and reloads each context on `SIGHUP`."""

from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from starpulse.runtime.config import load
from starpulse.runtime.contexts import _SharedStore, run_contexts

WAIT_S = 5.0
BACKOFF_S = (0.02, 0.05)


def thread_names() -> set[str]:
    return {t.name for t in threading.enumerate()}


def folds() -> int:
    return sum(t.name == "read-model-follow" for t in threading.enumerate())


class Process:
    """`run_contexts` on a thread, with a `hold` that records the reload `SIGHUP` would run."""

    def __init__(self, names: list[str], starters: dict[str, Callable[[threading.Event], Callable[[], None]]]) -> None:
        self.stop = threading.Event()
        self.reload: Callable[[], None] | None = None
        self.held = threading.Event()
        self.raised: list[BaseException] = []
        self._names = names
        self._starters = starters
        self.thread = threading.Thread(target=self._run, name="process", daemon=True)

    def _hold(self, stop: threading.Event, reload: Callable[[], None]) -> None:
        self.reload = reload
        self.held.set()
        stop.wait()

    def _run(self) -> None:
        try:
            run_contexts(
                load(None), None, self._names, self.stop, starters=self._starters, hold=self._hold, backoff=BACKOFF_S
            )
        except BaseException as exc:  # a context that takes the process down is the failure under test
            self.raised.append(exc)

    def context_thread(self, name: str) -> threading.Thread | None:
        return next((t for t in threading.enumerate() if t.name == f"ctx-{name}"), None)


@pytest.fixture
def process() -> Iterator[Callable[..., Process]]:
    made: list[Process] = []

    def make(starters: dict[str, Callable[[threading.Event], Callable[[], None]]]) -> Process:
        running = Process(list(starters), starters)
        made.append(running)
        running.thread.start()
        return running

    yield make
    for running in made:
        running.stop.set()
        running.thread.join(WAIT_S)


def test_a_context_that_raises_restarts_after_a_backoff_while_the_others_keep_their_threads(
    process: Callable[..., Process],
) -> None:
    steady_calls: list[int] = []
    tries: list[float] = []
    recovered = threading.Event()

    def steady(stop: threading.Event) -> Callable[[], None]:
        steady_calls.append(threading.get_ident())
        return lambda: None

    def flaky(stop: threading.Event) -> Callable[[], None]:
        tries.append(time.monotonic())
        if len(tries) < 3:
            raise ValueError("the board is not readable yet")
        recovered.set()
        return lambda: None

    running = process({"steady": steady, "flaky": flaky})
    assert running.held.wait(WAIT_S)
    before = running.context_thread("steady")
    assert before is not None

    assert recovered.wait(WAIT_S)

    assert len(tries) == 3
    assert tries[1] - tries[0] >= BACKOFF_S[0]
    assert tries[2] - tries[1] >= BACKOFF_S[0]
    assert len(steady_calls) == 1
    assert running.context_thread("steady") is before
    assert running.thread.is_alive()
    assert running.raised == []


def test_sighup_reloads_each_started_context_and_one_failing_reload_skips_none(process: Callable[..., Process]) -> None:
    reloaded: list[str] = []

    def starter(name: str, fail: bool = False) -> Callable[[threading.Event], Callable[[], None]]:
        def reload() -> None:
            reloaded.append(name)
            if fail:
                raise RuntimeError("reload failed")

        return lambda stop: reload

    running = process({"first": starter("first", fail=True), "second": starter("second")})
    assert running.held.wait(WAIT_S)
    deadline = time.monotonic() + WAIT_S
    while running.context_thread("second") is None and time.monotonic() < deadline:
        time.sleep(0.01)

    assert running.reload is not None
    running.reload()

    assert sorted(reloaded) == ["first", "second"]


def test_stopping_the_process_stops_every_context(process: Callable[..., Process]) -> None:
    stops: dict[str, threading.Event] = {}

    def starter(name: str) -> Callable[[threading.Event], Callable[[], None]]:
        def start(stop: threading.Event) -> Callable[[], None]:
            stops[name] = stop
            return lambda: None

        return start

    running = process({"one": starter("one"), "two": starter("two")})
    assert running.held.wait(WAIT_S)

    running.stop.set()
    running.thread.join(WAIT_S)

    assert not running.thread.is_alive()
    assert all(stop.wait(WAIT_S) for stop in stops.values())
    assert running.context_thread("one") is None


def test_a_context_that_never_starts_leaves_no_reload_to_run(process: Callable[..., Process]) -> None:
    def never(stop: threading.Event) -> Callable[[], None]:
        raise ValueError("config invalid")

    running = process({"never": never})
    assert running.held.wait(WAIT_S)

    assert running.reload is not None
    running.reload()  # nothing to reload and nothing raised
    assert running.raised == []


def test_the_default_starters_fold_the_board_once_for_every_context(tmp_path: Path) -> None:
    config = tmp_path / "starpulse.toml"
    config.write_text('[board]\ntype = "tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n')
    stop = threading.Event()
    held = threading.Event()
    before = folds()

    def hold(stop: threading.Event, reload: Callable[[], None]) -> None:
        held.set()
        stop.wait()

    thread = threading.Thread(
        target=run_contexts,
        args=(load(config), config, ["board", "pulls", "scheduler", "runs", "flow-metrics", "search"], stop),
        kwargs={"hold": hold, "backoff": BACKOFF_S},
        daemon=True,
    )
    thread.start()
    try:
        assert held.wait(WAIT_S)
        names = {f"ctx-{n}" for n in ("board", "pulls", "scheduler", "runs", "flow-metrics", "search")}
        deadline = time.monotonic() + WAIT_S
        while time.monotonic() < deadline and not (names <= thread_names() and folds() > before):
            time.sleep(0.02)
        time.sleep(0.5)  # a second fold, if a context built its own, has started by now

        assert names <= thread_names()
        assert folds() - before == 1
    finally:
        stop.set()
        thread.join(WAIT_S)


def test_every_context_gets_the_one_history_store_the_first_built(tmp_path: Path) -> None:
    built: list[object] = []

    def build(config: object, base: Path, machines: dict) -> object:
        built.append(object())
        return built[-1]

    store = _SharedStore(build)
    got: list[object] = []
    threads = [threading.Thread(target=lambda: got.append(store(None, tmp_path, {}))) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT_S)

    assert len(built) == 1
    assert got == built * 8


STARTS_ROOT = Path(__file__).parents[3] / "starpulse"


@pytest.mark.parametrize(
    "bin_path",
    sorted(p for p in STARTS_ROOT.glob("*/bin/*_worker.py") if p.name != "api_worker.py"),
    ids=lambda p: p.stem,
)
def test_every_context_bin_but_the_api_exposes_start(bin_path: Path) -> None:
    module = importlib.import_module(f"starpulse.{bin_path.parent.parent.name}.bin.{bin_path.stem}")

    assert callable(getattr(module, "start", None))
