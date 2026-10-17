"""A write the board refuses is counted and not tried again until the task's facts change; latency is exported."""

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.pulls.pulls import PullStore
from starpulse.tests.task_actor_kit import GATED, PR_ONE, Board, Criteria, pull, running, until


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

    board.put(
        task("TASK-1", "Review", references=(PR_ONE,), dependencies=("TASK-9",))
    )  # a change that is no fact it waits on
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


def test_a_criterion_that_cannot_be_evaluated_is_exported_and_not_evaluated_again_until_stale(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Ready", description=GATED), task("TASK-2", "Ready", description=GATED))
    evaluate = Criteria("error")

    actor = running(board, store, stop, evaluate=evaluate, fresh_s=60.0)

    assert until(lambda: board.moved() == [("TASK-1", "waiting"), ("TASK-2", "waiting")])
    exposition = actor.exposition()
    assert "# TYPE starpulse_task_actor_criteria_errors gauge" in exposition
    assert _sample(exposition, 'starpulse_task_actor_criteria_errors{task="TASK-1"}') == 1
    assert not until(lambda: evaluate.asked["TASK-1"] > 1, within=0.3)


def test_the_projection_and_the_store_to_actor_handoff_are_exported_as_histograms(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(PR_ONE,)))
    store.save([pull(1, state="OPEN")])
    actor = running(board, store, stop)
    actor.timed_projection(lambda: None)()
    store.save([pull(1, state="MERGED")])

    actor.store_changed()

    assert until(lambda: board.moved() == [("TASK-1", "done")])
    exposition = actor.exposition()
    for name in ("projection", "handoff"):
        assert f"# TYPE starpulse_task_actor_{name}_seconds histogram" in exposition
        assert _sample(exposition, f"starpulse_task_actor_{name}_seconds_count") == 1
