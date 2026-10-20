"""`starpulse worker forwarding` runs the forwarder alone, and keeps what `serve` shows of it in the event log."""

import functools
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import select

from starpulse._internal.config.config import load
from starpulse._internal.eventlog import events
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.eventlog.summaries import Summariser, summary_basis
from starpulse._internal.hub import forward, forward_report
from starpulse._internal.server import forwarding_worker, worker
from starpulse._internal.server.assembly import assemble
from starpulse.tests import fake_board

BOARD = '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'
FORWARD = '[forward]\nurl = "https://hub.example.test"\ntoken_env = "HUB_TOKEN"\n'
WAIT_S = 5.0


class Hub:
    """Stands where the network is: records each POST and answers from `answers`, then 200."""

    def __init__(self) -> None:
        self.answers: list[int | OSError] = []
        self.tasks: list[str] = []

    def __call__(self, url: str, token: str, body: bytes) -> tuple[int, dict]:
        answer = self.answers.pop(0) if self.answers else 200
        if isinstance(answer, OSError):
            raise answer
        if answer == 200:
            self.tasks += [e["fields"]["task"] for e in json.loads(body)["events"] if "task" in e["fields"]]
        return answer, {}


def _eventually(ready: Callable[[], object]) -> bool:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(0.02)
    return False


def _move(log: EventLog, task: str) -> None:
    events.publish("board", "MOVED", actor="ana", task=task, now=1.0, log=log)


@pytest.fixture
def hub() -> Hub:
    return Hub()


@pytest.fixture
def held() -> list[threading.Event]:
    return []


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hub: Hub, held: list[threading.Event]):
    """`worker.main` on `text`, holding returns at once; yields the log the worker shares with `serve`."""
    monkeypatch.setattr(fake_board, "BUILT", [])
    monkeypatch.setenv("HUB_TOKEN", "secret")
    monkeypatch.setattr(forward, "Forwarder", functools.partial(forward.Forwarder, send=hub, interval=0.02))
    monkeypatch.setattr(forwarding_worker, "hold", lambda stop, reload: held.append(stop))

    def start(text: str = FORWARD + BOARD) -> EventLog:
        config = tmp_path / "starpulse.toml"
        config.write_text(text)
        worker.main(["forwarding", "--config", str(config)])
        return EventLog(f"sqlite:///{(tmp_path / 'starpulse-history.sqlite').resolve()}")

    yield start
    for stop in held:
        stop.set()


def test_the_worker_sends_the_log_to_the_hub(run, hub: Hub) -> None:
    log = run()

    _move(log, "T-1")

    assert _eventually(lambda: hub.tasks == ["T-1"])


def test_the_worker_keeps_what_the_page_shows_of_it_in_the_log(run, hub: Hub) -> None:
    hub.answers = [503] * 10_000  # the hub stays down until the test lets it up
    log = run()
    _move(log, "T-1")

    def kept() -> dict:
        return log.setting(forward_report.RUNTIME) or {}

    assert _eventually(lambda: "503" in (kept().get("problem") or ""))
    hub.answers.clear()
    assert _eventually(lambda: kept().get("lastSent") and kept()["problem"] is None)


def test_a_restarted_worker_neither_drops_nor_repeats_a_forwarded_event(
    run, hub: Hub, held: list[threading.Event], tmp_path: Path
) -> None:
    log = run()
    _move(log, "T-1")
    assert _eventually(lambda: hub.tasks == ["T-1"])
    store = HistoryStore(f"sqlite:///{(tmp_path / 'starpulse-history.sqlite').resolve()}", {})
    first = store.checkpoints.load("forward:https://hub.example.test")[0]
    for stop in held:
        stop.set()
    time.sleep(0.2)  # the forwarder thread sees the stop

    _move(log, "T-2")  # arrives while no worker runs
    run()

    assert _eventually(lambda: hub.tasks == ["T-1", "T-2"])
    time.sleep(0.2)
    assert hub.tasks == ["T-1", "T-2"]  # T-1 once, T-2 once
    assert store.checkpoints.load("forward:https://hub.example.test")[0] > first


def test_a_worker_with_no_forward_table_refuses_to_start(run) -> None:
    with pytest.raises(SystemExit) as refusal:
        run(BOARD)

    assert refusal.value.code == 1


def test_starting_the_worker_leaves_the_summaries_the_other_workers_folded(run, tmp_path: Path) -> None:
    """Summaries folded under no machines differ from the ones every other worker folds, so each start would rebuild
    them all over and set the other workers rebuilding against it."""
    config = tmp_path / "starpulse.toml"
    config.write_text(FORWARD + BOARD)
    _, feed = assemble(load(config), tmp_path, None, [])
    folded = HistoryStore(f"sqlite:///{(tmp_path / 'starpulse-history.sqlite').resolve()}", feed.machines)

    run()

    with folded.engine.connect() as db:
        assert db.execute(select(summary_basis.c.fingerprint)).scalar() == Summariser(feed.machines).fingerprint()
