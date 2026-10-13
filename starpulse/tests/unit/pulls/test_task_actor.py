"""A write the board refuses is counted and not tried again until the task's facts change; latency is exported."""

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.pulls.pulls import PullStore
from starpulse.tests.task_actor_kit import PR_ONE, Board, pull, running, until


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = threading.Event()
    yield event
    event.set()


def _sample(text: str, name: str) -> float:
    return next(float(line.split()[-1]) for line in text.splitlines() if line.startswith(name))


def test_a_refused_write_is_counted_and_not_retried_until_the_tasks_facts_change(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(PR_ONE,)))
    board.refuse = True
    store.save([pull(1, state="MERGED")])
    actor = running(board, store, stop)
    assert _sample(actor.exposition(), "starpulse_task_actor_refusals_total") == 1

    board.put(task("TASK-1", "Review", references=(PR_ONE,), dependencies=("TASK-9",)))  # a change that is no fact it waits on
    store.save([pull(1, state="MERGED")])
    actor.pulls_changed()
    assert len(board.writes) == 1

    store.save([pull(1, state="MERGED", sha="b" * 40)])  # the merge commit changed: the facts did
    actor.pulls_changed()

    assert until(lambda: len(board.writes) == 2)
    assert _sample(actor.exposition(), "starpulse_task_actor_refusals_total") == 2


def test_the_latency_from_a_fact_to_the_landed_write_is_exported_as_a_histogram(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(PR_ONE,)))
    store.save([pull(1, state="MERGED")])

    exposition = running(board, store, stop).exposition()

    assert "# TYPE starpulse_task_actor_latency_seconds histogram" in exposition
    assert _sample(exposition, "starpulse_task_actor_latency_seconds_count") == 1
    assert _sample(exposition, 'starpulse_task_actor_latency_seconds_bucket{le="+Inf"}') == 1
