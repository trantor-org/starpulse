"""`starpulse worker runs` runs the Runs context alone, and keeps the workflows `serve` draws in the event log."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from starpulse._internal.eventlog import lane_events
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.runs import projection, run_events
from starpulse._internal.runs.push_runs import PUSHED_INSTANCE
from starpulse._internal.server import runs_worker, server, worker
from starpulse.tests import fake_board

BOARD = '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'
RUNS = '[[runs]]\nname = "dagu"\ntype = "dagu"\nurl = "http://dagu.invalid"\n'
TRIGGER = '[[triggers]]\non = "lane"\nstart = "dagu/reconcile"\n'
CONFIG = RUNS + TRIGGER + BOARD
DAGS = [{"name": "ci", "status": "success", "runId": "1", "startedAt": "", "finishedAt": "", "steps": []}]
WAIT_S = 5.0
START = 1_700_000_000.0


class Dagu:
    """The runs adapter module `runs_adapter` resolves: it reports one workflow and starts one run per call."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.followed: list[str] = []

    def start(self, url: str) -> Callable[[str], str]:
        def begin(workflow: str) -> str:
            self.started.append(workflow)
            return f"run-{len(self.started)}"

        return begin

    def follow(self, url: str, sink: object, log: object) -> None:
        self.followed.append(url)
        sink.set_dags(DAGS, None)


def _eventually(ready: Callable[[], object]) -> bool:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(0.05)
    return False


def _move(log: EventLog, task: str, at: float) -> None:
    lane_events.append(log, f"{task}-done-{at}", task, "done", at)


def _push(log: EventLog, workflow: str) -> None:
    log.append(run_events.STREAM, run_events.entry("start", workflow, "r1", "running", now=START))


def _pushed(log: EventLog) -> list[str]:
    """The names of the pushed workflows the worker has kept in the log."""
    kept = (log.setting(projection.PROJECTION) or {}).get(PUSHED_INSTANCE, {})
    return sorted(dag["name"] for dag in kept.get("dags", []))


@pytest.fixture
def dagu() -> Dagu:
    return Dagu()


@pytest.fixture
def held() -> list[threading.Event]:
    return []


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dagu: Dagu, held: list[threading.Event]):
    """`worker.main` on `text`, holding returns at once; yields the log the worker shares with `serve`."""
    monkeypatch.setattr(fake_board, "BUILT", [])
    monkeypatch.setattr(server, "runs_adapter", lambda kind: dagu)
    monkeypatch.setattr(runs_worker, "hold", lambda stop, reload: held.append(stop))

    def start(text: str = CONFIG) -> EventLog:
        config = tmp_path / "starpulse.toml"
        config.write_text(text)
        worker.main(["runs", "--config", str(config)])
        url = f"sqlite:///{(tmp_path / 'starpulse-history.sqlite').resolve()}"
        if "[[triggers]]" in text:  # a move appended before the reader takes its place at the head is never read
            store = HistoryStore(url, {})
            assert _eventually(lambda: store.cursor("triggers") is not None)
        return EventLog(url)

    yield start
    for stop in held:
        stop.set()


def _end(held: list[threading.Event]) -> None:
    """Stop every worker started so far and wait for the trigger reader of each to return."""
    for stop in held:
        stop.set()
    for thread in threading.enumerate():
        if thread.name == "board-triggers":
            thread.join(WAIT_S)


def test_the_worker_follows_each_instance_and_keeps_its_workflows_in_the_log(run, dagu: Dagu) -> None:
    log = run()

    assert dagu.followed == ["http://dagu.invalid"]
    assert log.setting(projection.PROJECTION)["dagu"]["dags"] == DAGS


def test_a_board_event_a_trigger_matches_starts_its_workflow(run, dagu: Dagu) -> None:
    log = run()

    _move(log, "TASK-1", 100.0)

    assert _eventually(lambda: dagu.started)
    assert dagu.started == ["reconcile"]


def test_a_pushed_run_reaches_the_log_as_the_pushed_instance(run) -> None:
    log = run()

    _push(log, "nightly")

    assert _eventually(lambda: _pushed(log) == ["nightly"])


def test_a_worker_with_no_trigger_starts_no_trigger_reader(run, dagu: Dagu) -> None:
    before = {t for t in threading.enumerate() if t.name == "board-triggers"}  # a stopped worker's may still be exiting
    log = run(RUNS + BOARD)

    _move(log, "TASK-1", 100.0)
    time.sleep(0.3)

    assert dagu.started == []
    assert {t for t in threading.enumerate() if t.name == "board-triggers"} <= before


def test_a_restarted_worker_neither_drops_nor_repeats_a_trigger_start_or_a_pushed_run(
    run, dagu: Dagu, held: list[threading.Event], tmp_path: Path
) -> None:
    log = run()
    _move(log, "TASK-1", 100.0)
    _push(log, "nightly")
    assert _eventually(lambda: dagu.started)
    _end(held)

    _move(log, "TASK-2", 101.0)  # arrives while no worker runs
    _push(log, "weekly")
    run()

    assert _eventually(lambda: len(dagu.started) == 2)
    assert _eventually(lambda: _pushed(log) == ["nightly", "weekly"])
    _end(held)
    assert dagu.started == ["reconcile", "reconcile"]  # TASK-1 once, TASK-2 once
    assert HistoryStore(f"sqlite:///{(tmp_path / 'starpulse-history.sqlite').resolve()}", {}).cursor("triggers")
