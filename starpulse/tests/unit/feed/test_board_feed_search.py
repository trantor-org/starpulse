"""The feed keeps the search index current from what an adapter places and retracts."""

import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.feed.search import SearchIndex
from starpulse.contracts.adapters import BoardTask, TaskKeys


def _task(task_id: str = "PROJ-1", **fields: object) -> BoardTask:
    return BoardTask.model_validate({"id": task_id, "team": "demo", "title": "t", "lane": "to_do", **fields})


@pytest.fixture
def index(tmp_path: Path) -> SearchIndex:
    opened = SearchIndex.open(create_engine(f"sqlite:///{tmp_path / 'search.sqlite'}"))
    assert opened is not None
    return opened


def _found(index: SearchIndex, query: str) -> list[str]:
    return [hit["task"] for hit in index.search(query)]


def test_a_placed_task_is_found_and_a_retracted_one_is_not(index: SearchIndex) -> None:
    feed = BoardFeed()
    feed.index_tasks(index)

    feed.put(_task("PROJ-1", title="Drain the queue"))
    assert _found(index, "drain") == ["PROJ-1"]

    feed.retract("PROJ-1")
    assert _found(index, "drain") == []


def test_an_edit_the_board_does_not_draw_is_still_indexed(index: SearchIndex) -> None:
    feed = BoardFeed()
    feed.index_tasks(index)
    feed.put(_task("PROJ-1", title="Drain"))

    feed.put(_task("PROJ-1", title="Drain", acceptance_criteria=("Pager stays quiet",), notes="vault renewed"))

    assert _found(index, "pager") == ["PROJ-1"]
    assert _found(index, "vault") == ["PROJ-1"]


def test_a_task_outside_the_declared_key_scheme_is_not_indexed(index: SearchIndex) -> None:
    keys = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"(PROJ-\d+)"))
    feed = BoardFeed(keys=keys)
    feed.index_tasks(index)

    feed.put(_task("OTHER-1", title="Drain"))

    assert _found(index, "drain") == []


def test_an_index_that_fails_does_not_stop_the_task_being_placed() -> None:
    class Broken:
        def index(self, task: BoardTask) -> None:
            raise RuntimeError("disk full")

        def remove(self, task_id: str) -> None:
            raise RuntimeError("disk full")

    feed = BoardFeed()
    feed.index_tasks(Broken())  # type: ignore[arg-type]

    feed.put(_task("PROJ-1"))
    feed.retract("PROJ-1")

    assert feed.task("PROJ-1") is None


def test_a_feed_with_no_index_places_tasks_as_before() -> None:
    feed = BoardFeed()

    feed.put(_task("PROJ-1"))

    assert feed.task("PROJ-1") is not None
