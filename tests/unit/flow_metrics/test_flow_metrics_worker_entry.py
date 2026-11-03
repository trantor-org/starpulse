"""`starpulse worker flow-metrics` records the log's machine events into the history store, alone."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import select
from starpulse.event_log import events
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore, _machine_events
from starpulse.runtime import assembly, worker

from tests import fake_board

BOARD = '[board]\ntype = "tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'
WAIT_S = 30.0  # the worker is a spawned child; a loaded CI runner took over 5 s to start it


def _eventually(ready: Callable[[], object]) -> bool:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(0.02)
    return False


def _move(log: EventLog, task: str) -> None:
    events.publish("board", "MOVED", actor="ana", task=task, now=1.0, log=log)


def _recorded(store: HistoryStore) -> list[str]:
    with store.engine.connect() as db:
        return [row.task for row in db.execute(select(_machine_events.c.task).order_by(_machine_events.c.id))]


@pytest.fixture
def held() -> list[threading.Event]:
    return []


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held: list[threading.Event]):
    """`worker.main` on `text`, holding returns at once; yields the log and store the worker shares with `serve`."""
    monkeypatch.setattr(fake_board, "BUILT", [])
    monkeypatch.setattr("starpulse.runtime.hold.hold", lambda stop, reload: held.append(stop))
    url = f"sqlite:///{(tmp_path / 'starpulse-history.sqlite').resolve()}"

    def start(text: str = BOARD) -> tuple[EventLog, HistoryStore]:
        config = tmp_path / "starpulse.toml"
        config.write_text(text)
        worker.main(["flow-metrics", "--config", str(config)])
        return EventLog(url), HistoryStore(url, {})

    yield start
    for stop in held:
        stop.set()


def test_the_worker_records_the_logs_machine_events_into_the_history(run) -> None:
    log, store = run()

    _move(log, "T-1")

    assert _eventually(lambda: _recorded(store) == ["T-1"])


def test_a_restarted_worker_neither_drops_nor_repeats_a_history_row(
    run, held: list[threading.Event], tmp_path: Path
) -> None:
    log, store = run()
    _move(log, "T-1")
    assert _eventually(lambda: _recorded(store) == ["T-1"])
    first = store.checkpoints.load("machine:events")[0]
    for stop in held:
        stop.set()
    time.sleep(0.2)  # the recorder thread sees the stop

    _move(log, "T-2")  # arrives while no worker runs
    run()

    assert _eventually(lambda: _recorded(store) == ["T-1", "T-2"])
    time.sleep(0.2)
    assert _recorded(store) == ["T-1", "T-2"]  # T-1 once, T-2 once
    assert store.checkpoints.load("machine:events")[0] > first


def test_the_retired_history_context_name_is_refused() -> None:
    from starpulse.runtime.worker import worker_parser

    with pytest.raises(SystemExit) as refused:
        worker_parser().parse_args(["history"])
    assert refused.value.code == 2
