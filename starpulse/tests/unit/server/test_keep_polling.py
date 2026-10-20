"""`serve` keeps the pull poller running: a crash is logged and the poller started again after a delay."""

import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.pulls.pull_store import PullSync
from starpulse._internal.pulls.pulls import PullStore
from starpulse._internal.server import server
from starpulse.tests.unit.pulls.test_pull_store import Github

WAIT_S = 5.0
DELAYS = (0.01, 0.04)


class Crashing(BoardFeed):
    """A feed whose replay wait raises `crashes` times, which ends the poller's run with an exception."""

    def __init__(self, crashes: int) -> None:
        super().__init__()
        self.crashes = crashes

    def wait_replayed(self, timeout: float | None = None) -> bool:
        if self.crashes:
            self.crashes -= 1
            raise RuntimeError("the poller was killed")
        return super().wait_replayed(timeout)


def test_a_poller_killed_by_an_exception_is_started_again_and_its_next_refresh_writes_rows(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    feed = Crashing(crashes=2)
    feed.put(task("PROJ-1", "In Progress", references=["https://github.com/acme/widgets/pull/1"]))
    store = PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))
    github = Github()
    github.add(1)
    stop, running = threading.Event(), threading.Event()
    sync = PullSync(store, feed, (), github, lambda: 100.0, stop=stop)
    thread = threading.Thread(target=server.keep_polling, args=(sync, stop, running, DELAYS), daemon=True)

    thread.start()
    assert sync.request("acme/widgets", 1) is True
    deadline = time.monotonic() + WAIT_S
    while not store.find() and time.monotonic() < deadline:
        time.sleep(0.01)
    stop.set()
    thread.join(WAIT_S)

    assert [pull["number"] for pull in store.find()] == [1]
    assert feed.crashes == 0
    assert caplog.text.count("the poller crashed") == 2
    assert not thread.is_alive()
    assert not running.is_set()


def test_a_poller_that_returns_is_not_started_again() -> None:
    runs: list[int] = []

    class Sync:
        def run_forever(self) -> None:
            runs.append(1)

    server.keep_polling(Sync(), threading.Event(), threading.Event(), DELAYS)  # type: ignore[arg-type]

    assert runs == [1]
