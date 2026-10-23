"""`starpulse worker dagu` is the Dagu Adapter as an opt-in process: `serve` starts none of it, and the page shows when it is down."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from starpulse._internal.config.config import load
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.runs import opt_in, projection
from starpulse._internal.server import dagu_worker, runs_worker, server, supervisor, worker
from starpulse.tests import fake_board

BOARD = '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'
RUNS = '[[runs]]\nname = "dagu"\ntype = "dagu"\nurl = "http://dagu.invalid"\n'
CONFIG = RUNS + BOARD
DAGS = [{"name": "ci", "status": "success", "runId": "1", "startedAt": "", "finishedAt": "", "steps": []}]
WAIT_S = 5.0
NOW = 1_700_000_000.0


class Dagu:
    """The adapter module `runs_adapter` resolves for `dagu`: it names the worker that runs it and reports one workflow."""

    WORKER = "dagu"

    def __init__(self) -> None:
        self.followed: list[str] = []

    def follow(self, url: str, sink: object, log: object) -> None:
        self.followed.append(url)
        sink.set_dags(DAGS, None)


class Feed:
    """The serving feed's `set_dags`, recording what the page is told."""

    def __init__(self) -> None:
        self.told: dict[str, tuple] = {}

    def set_dags(self, instance: str, dags: list, error: str | None, pools: object, startable: object) -> None:
        self.told[instance] = (dags, error)


def _eventually(ready: Callable[[], object]) -> bool:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{(tmp_path / 'starpulse-history.sqlite').resolve()}")


@pytest.fixture
def dagu() -> Dagu:
    return Dagu()


@pytest.fixture
def held() -> list[threading.Event]:
    return []


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dagu: Dagu, held: list[threading.Event], log: EventLog):
    """`worker.main` of a context on the config, holding returns at once."""
    monkeypatch.setattr(fake_board, "BUILT", [])
    monkeypatch.setattr(server, "runs_adapter", lambda kind: dagu)
    monkeypatch.setattr(runs_worker, "hold", lambda stop, reload: held.append(stop))
    monkeypatch.setattr(dagu_worker, "hold", lambda stop, reload: held.append(stop))

    def start(context: str) -> None:
        config = tmp_path / "starpulse.toml"
        config.write_text(CONFIG)
        worker.main([context, "--config", str(config)])

    yield start
    for stop in held:
        stop.set()


def test_serve_supervises_no_dagu_worker(tmp_path: Path) -> None:
    path = tmp_path / "starpulse.toml"
    path.write_text(CONFIG)

    commands = supervisor.worker_commands(load(path), path)

    assert "dagu" not in commands
    assert all("dagu" not in command[-3:] for command in commands.values())


def test_the_dagu_worker_follows_the_instance_and_keeps_its_workflows_in_the_log(run, dagu: Dagu, log: EventLog) -> None:
    run("dagu")

    assert dagu.followed == ["http://dagu.invalid"]
    assert log.setting(projection.PROJECTION)["dagu"]["dags"] == DAGS


def test_the_runs_worker_leaves_the_dagu_instance_to_the_dagu_worker(run, dagu: Dagu) -> None:
    run("runs")

    assert dagu.followed == []


def test_the_dagu_worker_beats_while_it_runs(run, log: EventLog) -> None:
    run("dagu")

    assert _eventually(lambda: opt_in.problem(log, "dagu")() is None)


def test_the_page_is_told_when_the_adapter_never_reported(log: EventLog) -> None:
    feed = Feed()

    projection.Projected(log, feed, watched={"dagu": opt_in.problem(log, "dagu", lambda: NOW)}).apply()

    assert feed.told["dagu"] == ([], "the dagu worker has not reported")


def test_the_page_shows_workflows_as_healthy_while_the_adapter_beats(log: EventLog) -> None:
    projection.Publisher(log).report("dagu", DAGS, None, None, None)
    opt_in.beat(log, "dagu", lambda: NOW)
    feed = Feed()

    projection.Projected(log, feed, watched={"dagu": opt_in.problem(log, "dagu", lambda: NOW + 10)}).apply()

    assert feed.told["dagu"] == (DAGS, None)


def test_the_page_is_told_when_the_adapter_stops_beating(log: EventLog) -> None:
    projection.Publisher(log).report("dagu", DAGS, None, None, None)
    opt_in.beat(log, "dagu", lambda: NOW)
    feed = Feed()

    projection.Projected(log, feed, watched={"dagu": opt_in.problem(log, "dagu", lambda: NOW + 120)}).apply()

    assert feed.told["dagu"] == (DAGS, "the dagu worker last reported 120s ago")


def test_an_adapter_that_stops_silently_is_flagged_without_any_new_report(
    log: EventLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(projection, "RECHECK_S", 0.05)
    clock = [NOW]
    opt_in.beat(log, "dagu", lambda: NOW)
    feed = Feed()
    stop = threading.Event()
    projection.Projected(log, feed, watched={"dagu": opt_in.problem(log, "dagu", lambda: clock[0])}).follow(stop)

    clock[0] = NOW + 120

    try:
        assert _eventually(lambda: feed.told.get("dagu", (None, None))[1] == "the dagu worker last reported 120s ago")
    finally:
        stop.set()
