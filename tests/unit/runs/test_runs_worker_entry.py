"""`starpulse worker runs` runs the Runs context alone, and keeps the workflows `serve` draws in the event log."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from starpulse.event_log.event_log import EventLog
from starpulse.runs.application.queries import projection
from starpulse.runs.application.queries.push_runs import PUSHED_INSTANCE
from starpulse.runs.model import run_events
from starpulse.runtime import server, worker

from tests import fake_board

BOARD = '[board]\ntype = "tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'
RUNS = '[[runs]]\nname = "dagu"\ntype = "dagu"\nurl = "http://dagu.invalid"\n'
CONFIG = RUNS + BOARD
DAGS = [{"name": "ci", "status": "success", "runId": "1", "startedAt": "", "finishedAt": "", "steps": []}]
WAIT_S = 5.0
START = 1_700_000_000.0


class Dagu:
    """The runs adapter module `runs_adapter` resolves: it reports one workflow."""

    def __init__(self) -> None:
        self.followed: list[str] = []

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


def _push(log: EventLog, workflow: str) -> None:
    log.publish(run_events.STREAM, run_events.entry("StepStarted", workflow, "r1", "running", now=START))


def _pushed(log: EventLog) -> list[str]:
    """The names of the pushed workflows the worker has kept in the log."""
    kept = (log.state(projection.PROJECTION)[1] or {}).get(PUSHED_INSTANCE, {})
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
    monkeypatch.setattr("starpulse.runtime.hold.hold", lambda stop, reload: held.append(stop))

    def start(text: str = CONFIG) -> EventLog:
        config = tmp_path / "starpulse.toml"
        config.write_text(text)
        worker.main(["runs", "--config", str(config)])
        url = f"sqlite:///{(tmp_path / 'starpulse-history.sqlite').resolve()}"
        return EventLog(url)

    yield start
    for stop in held:
        stop.set()


def test_the_worker_follows_each_instance_and_keeps_its_workflows_in_the_log(run, dagu: Dagu) -> None:
    log = run()

    assert dagu.followed == ["http://dagu.invalid"]
    assert log.state(projection.PROJECTION)[1]["dagu"]["dags"] == DAGS


def test_a_pushed_run_reaches_the_log_as_the_pushed_instance(run) -> None:
    log = run()

    _push(log, "nightly")

    assert _eventually(lambda: _pushed(log) == ["nightly"])


def test_a_restarted_worker_neither_drops_nor_repeats_a_pushed_run(run, held: list[threading.Event]) -> None:
    log = run()
    _push(log, "nightly")
    assert _eventually(lambda: _pushed(log) == ["nightly"])
    for stop in held:
        stop.set()

    _push(log, "weekly")  # arrives while no worker runs
    run()

    assert _eventually(lambda: _pushed(log) == ["nightly", "weekly"])
