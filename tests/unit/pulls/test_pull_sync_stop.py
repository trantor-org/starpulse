"""The pull store's refresh thread and the board-unblock loop end when the stop event they were built with is set."""

import threading

from sqlalchemy import create_engine
from starpulse.board.board_feed import BoardFeed
from starpulse.pulls.adapters.outbound.pull_store import PullSync
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.runtime import server
from starpulse.runtime.adapter_kit import task

WAIT_S = 5.0


def _sync(stop: threading.Event, graphql=lambda repo, query: {}) -> PullSync:
    feed = BoardFeed()
    feed.put(task("PROJ-1", "In Progress", references=["https://github.com/acme/widgets/pull/1"]))
    return PullSync(PullStore(create_engine("sqlite://")), feed, (), graphql, lambda: 1.0, stop=stop)


def test_a_stopped_sync_serves_no_request() -> None:
    stop = threading.Event()
    stop.set()
    asked: list[str] = []

    def graphql(repo: str, query: str) -> dict:
        asked.append(repo)
        return {}

    sync = _sync(stop, graphql)
    sync.request("acme/widgets", 1)
    sync.run_forever()

    assert asked == []


def test_run_forever_returns_once_the_sync_is_stopped() -> None:
    stop = threading.Event()
    sync = _sync(stop)
    thread = threading.Thread(target=sync.run_forever, daemon=True)
    thread.start()

    stop.set()
    thread.join(WAIT_S)

    assert not thread.is_alive()


def test_the_unblock_loop_returns_once_it_is_stopped() -> None:
    stop = threading.Event()
    passes: list[bool] = []

    class Unblocker:
        def unblock(self) -> None:
            passes.append(True)

    thread = threading.Thread(target=server._keep_unblocked, args=(Unblocker(), BoardFeed(), stop, 3600.0), daemon=True)
    thread.start()
    stop.set()
    thread.join(WAIT_S)

    assert not thread.is_alive()
