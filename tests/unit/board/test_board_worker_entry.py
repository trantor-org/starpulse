"""`starpulse worker board` keeps the Board's writers (the Start Criteria dating and the lane reconcile), alone."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from starpulse.board.bin import board_worker
from starpulse.board.board_feed import BoardFeed
from starpulse.contracts import BoardTask
from starpulse.flow_metrics.history import HistoryStore
from starpulse.runtime import worker

from tests import fake_board
from tests.machines import MACHINES, ROLES

BOARD = '[board]\ntype = "tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'
WAIT_S = 5.0
BLOCK = """## Start Criteria

```yaml
start_criteria:
- id: soak
  kind: prom
  expr: time()
  at_least: 1
```
"""


def _eventually(ready: Callable[[], object]) -> bool:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def stop():
    stopping = threading.Event()
    yield stopping
    stopping.set()


def _store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)


def _feed(*tasks: BoardTask, clock: float = 100.0) -> BoardFeed:
    """A feed that has read its Board: the writers wait for that."""
    feed = BoardFeed(roles=ROLES, machines=MACHINES, clock=lambda: clock)
    feed.expect("0-0")
    for task in tasks:
        feed.put(task)
    return feed


def _task(lane: str, **fields: object) -> BoardTask:
    return BoardTask(id="T-1", team="demo", title="t", lane=lane, **fields)


def _met(task: str, description: str) -> list[dict]:
    return [{"id": "soak", "status": "met"}]


def test_the_writers_date_the_start_criteria_a_task_meets_and_keep_the_date(
    tmp_path: Path, stop: threading.Event
) -> None:
    store = _store(tmp_path)

    board_worker.start_writers(_feed(_task("waiting", description=BLOCK), clock=100.0), store, _met, stop)

    assert _eventually(lambda: store.criteria_met() == {"T-1": 100.0})


def test_a_restarted_writer_keeps_the_date_the_last_one_gave(tmp_path: Path, stop: threading.Event) -> None:
    store = _store(tmp_path)
    store.save_criteria_met({"T-1": 50.0})  # the last worker dated its criteria met
    calls: list[str] = []

    def evaluate(task: str, description: str) -> list[dict]:
        calls.append(task)
        return _met(task, description)

    for restart in range(2):
        feed = _feed(_task("waiting", description=BLOCK), clock=900.0 + restart)
        board_worker.start_writers(feed, store, evaluate, stop)
        assert _eventually(lambda: len(calls) > restart)
        assert store.criteria_met() == {"T-1": 50.0}


def test_the_writers_wait_for_the_board_to_be_read_before_they_forget_a_met_date(
    tmp_path: Path, stop: threading.Event
) -> None:
    store = _store(tmp_path)
    store.save_criteria_met({"T-1": 50.0})
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.expect("1-0")  # the stream has more to read than the feed has

    board_worker.start_writers(feed, store, _met, stop)
    time.sleep(0.2)

    assert store.criteria_met() == {"T-1": 50.0}


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch, stop: threading.Event) -> list[threading.Event]:
    held: list[threading.Event] = []
    monkeypatch.setattr("starpulse.runtime.hold.hold", lambda event, reload: held.append(event))
    return held


def test_the_board_worker_builds_the_board_starts_the_writers_and_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held: list[threading.Event]
) -> None:
    monkeypatch.setattr(fake_board, "BUILT", [])
    config = tmp_path / "starpulse.toml"
    config.write_text(BOARD)
    before = set(threading.enumerate())

    worker.main(["board", "--config", str(config)])

    assert len(held) == 1  # it reached the hold rather than exiting
    assert len(fake_board.BUILT) == 1
    assert "board-criteria" in {t.name for t in set(threading.enumerate()) - before}
    held[0].set()


def test_the_board_worker_under_the_read_model_starts_the_claim_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held: list[threading.Event]
) -> None:
    monkeypatch.setattr(fake_board, "SWEPT", [])
    config = tmp_path / "starpulse.toml"
    config.write_text("read_model = true\n" + BOARD)

    worker.main(["board", "--config", str(config)])

    assert len(fake_board.SWEPT) == 1  # the read model skips board.start, which is where the sweep began
    held[0].set()
