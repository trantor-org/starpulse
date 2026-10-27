"""`starpulse worker <dagu|github-actions|systemd>` is each run Adapter as an opt-in process: `serve` starts none of it, and the page shows when it is down."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from starpulse.event_log.event_log import EventLog
from starpulse.runs import dagu, github_actions, opt_in, projection, systemd
from starpulse.runtime import server, supervisor, worker
from starpulse.runtime.config import load

from tests import fake_board

BOARD = '[board]\ntype = "tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'
WORKERS = {"dagu": "dagu", "github_actions": "github-actions", "systemd": "systemd"}
ADAPTERS = {"dagu": dagu, "github_actions": github_actions, "systemd": systemd}


def config_of(kind: str) -> str:
    return f'[[runs]]\nname = "{kind}"\ntype = "{kind}"\nurl = "http://adapter.invalid"\n' + BOARD


DAGS = [
    {
        "name": "ci",
        "status": "succeeded",
        "runId": "1",
        "startedAt": "",
        "finishedAt": "",
        "steps": [],
        "schedule": [],
        "stats": None,
        "rerun": None,
    }
]
WAIT_S = 5.0
NOW = 1_700_000_000.0


class Adapter:
    """The adapter module `runs_adapter` resolves: it names the worker that runs it and reports one workflow."""

    def __init__(self, worker: str) -> None:
        self.WORKER = worker
        self.followed: list[str] = []

    def follow(self, url: str, sink: object, log: object) -> None:
        self.followed.append(url)
        sink.set_dags(DAGS, None)


class Feed:
    """The serving feed's `set_dags`, recording what the page is told."""

    def __init__(self) -> None:
        self.told: dict[str, tuple] = {}

    def set_dags(
        self, instance: str, dags: list, error: str | None, pools: object, startable: object, cpu: object = None
    ) -> None:
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


@pytest.fixture(params=sorted(WORKERS))
def kind(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def adapter(kind: str) -> Adapter:
    return Adapter(WORKERS[kind])


@pytest.fixture
def held() -> list[threading.Event]:
    return []


@pytest.fixture
def run(
    kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    adapter: Adapter,
    held: list[threading.Event],
    log: EventLog,
):
    """`worker.main` of a context on the config of `kind`, holding returns at once."""
    monkeypatch.setattr(fake_board, "BUILT", [])
    monkeypatch.setattr(server, "runs_adapter", lambda _kind: adapter)
    monkeypatch.setattr("starpulse.runtime.hold.hold", lambda stop, reload: held.append(stop))
    monkeypatch.setattr("starpulse.runtime.hold.hold", lambda stop, reload: held.append(stop))

    def start(context: str) -> None:
        config = tmp_path / "starpulse.toml"
        config.write_text(config_of(kind))
        worker.main([context, "--config", str(config)])

    yield start
    for stop in held:
        stop.set()


@pytest.mark.parametrize("module", ADAPTERS.items())
def test_each_shipped_adapter_names_its_opt_in_worker(module: tuple) -> None:
    kind, adapter = module

    assert opt_in.worker_of(adapter) == WORKERS[kind]


def test_serve_supervises_no_adapter_worker(kind: str, tmp_path: Path) -> None:
    path = tmp_path / "starpulse.toml"
    path.write_text(config_of(kind))

    commands = supervisor.worker_commands(load(path), path)

    assert WORKERS[kind] not in commands
    assert all(WORKERS[kind] not in command[-3:] for command in commands.values())


def test_the_worker_follows_the_instance_and_keeps_its_workflows_in_the_log(
    kind: str, run, adapter: Adapter, log: EventLog
) -> None:
    run(WORKERS[kind])

    assert adapter.followed == ["http://adapter.invalid"]
    assert log.state(projection.PROJECTION)[1][kind]["dags"] == DAGS


def test_the_runs_worker_leaves_the_instance_to_its_worker(run, adapter: Adapter) -> None:
    run("runs")

    assert adapter.followed == []


def test_the_worker_beats_while_it_runs(kind: str, run, log: EventLog) -> None:
    run(WORKERS[kind])

    assert _eventually(lambda: opt_in.problem(log, kind)() is None)


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
