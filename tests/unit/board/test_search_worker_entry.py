"""`starpulse worker search` catches the task search index's embeddings up, alone."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from starpulse.board.adapters import search as search_module
from starpulse.board.adapters.search import SearchIndex
from starpulse.board.model.search_config import Search
from starpulse.contracts.adapters import BoardTask
from starpulse.runtime import worker

from tests import fake_board

BOARD = '[board]\ntype = "tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'
SEARCH = '[search]\nembeddings_url = "http://embeddings.test/v1/embeddings"\nmodel = "m"\n'
WAIT_S = 5.0


def _eventually(ready: Callable[[], object]) -> bool:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def embedded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The texts the endpoint was asked to embed, in order; the worker polls every few milliseconds."""
    asked: list[str] = []

    def embed(self: SearchIndex, texts: list[str], timeout: float = 0) -> list[list[float]]:
        asked.extend(texts)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(SearchIndex, "_embed", embed)
    monkeypatch.setattr(search_module, "_POLL", 0.02)
    return asked


@pytest.fixture
def held() -> list[threading.Event]:
    return []


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held: list[threading.Event]):
    """`worker.main` on `text`, holding returns at once; yields the index the worker shares with `serve`."""
    monkeypatch.setattr(fake_board, "BUILT", [])
    monkeypatch.setattr("starpulse.runtime.hold.hold", lambda stop, reload: held.append(stop))
    url = f"sqlite:///{(tmp_path / 'starpulse-history.sqlite').resolve()}"

    def start(config_text: str = SEARCH + BOARD) -> SearchIndex:
        config = tmp_path / "starpulse.toml"
        config.write_text(config_text)
        worker.main(["search", "--config", str(config)])
        index = SearchIndex.open(create_engine(url), Search("http://embeddings.test/v1/embeddings", "m"))
        assert index is not None
        return index

    yield start
    for stop in held:
        stop.set()


def _task(task_id: str) -> BoardTask:
    return BoardTask.model_validate({"id": task_id, "team": "demo", "title": task_id, "lane": "to_do"})


def _vectors(index: SearchIndex) -> int:
    with index._engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM starpulse_task_vectors")).scalar_one()


def test_the_worker_embeds_the_tasks_the_index_holds(run, embedded: list[str]) -> None:
    index = run()

    index.index(_task("T-1"))

    assert _eventually(lambda: _vectors(index) == 1)
    assert [asked.splitlines()[0] for asked in embedded] == ["T-1"]


def test_a_restarted_worker_neither_drops_nor_repeats_an_embedding(
    run, embedded: list[str], held: list[threading.Event]
) -> None:
    index = run()
    index.index(_task("T-1"))
    assert _eventually(lambda: _vectors(index) == 1)
    for stop in held:
        stop.set()
    time.sleep(0.2)  # the embedding thread sees the stop

    index.index(_task("T-2"))  # arrives while no worker runs
    run()

    assert _eventually(lambda: _vectors(index) == 2)
    time.sleep(0.2)
    assert sorted(asked.splitlines()[0] for asked in embedded) == ["T-1", "T-2"]  # T-1 once, T-2 once


def test_a_worker_with_no_embeddings_url_starts_no_thread_and_holds(
    run, embedded: list[str], held: list[threading.Event]
) -> None:
    before = {t.name for t in threading.enumerate()}

    index = run(BOARD)
    index.index(_task("T-1"))

    assert len(held) == 1  # it reached the hold rather than exiting
    assert "search-embeddings" not in {t.name for t in threading.enumerate()} - before
    assert embedded == []
