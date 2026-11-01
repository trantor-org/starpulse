"""A write the board refuses is counted and not tried again until the task's facts change; latency is exported."""

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from starpulse.board.board_feed import BoardFeed
from starpulse.pulls.adapters.inbound.task_actor import ACTOR, ATTENTION_QUESTION, LINT_REFUSED, REGATE
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.runtime.adapter_kit import task

from tests.task_actor_kit import GATED, PR_ONE, PR_TWO, ROLES, Board, Criteria, pull, running, until


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


HEAD = "0" * 12  # the first twelve digits of a stand-in pull request's head commit
REFUSAL = "Waiting needs exactly one release gate"


def test_a_refused_release_to_ready_parks_the_task_in_needs_attention_with_the_refusal_as_its_reason(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(roles=ROLES), task("TASK-9", "Done"), task("TASK-1", "Waiting", dependencies=("TASK-9",)))
    board.refusing["ready"] = REFUSAL
    running(board, store, stop)

    assert until(lambda: len(board.moved()) == 2)
    assert board.moved() == [("TASK-1", "ready"), ("TASK-1", "needs_attention")]
    _, changes, _, _ = board.writes[1]
    reason = f"{REFUSAL}. Clear it so the task can return to Ready?"
    assert changes["description"].endswith(f"## Needs attention\n\n{reason}")


def test_a_repeated_refusal_for_the_same_task_and_reason_parks_the_task_once(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(roles=ROLES), task("TASK-9", "Done"), task("TASK-1", "Waiting", dependencies=("TASK-9",)))
    board.refusing["ready"] = REFUSAL
    actor = running(board, store, stop)
    assert until(lambda: len(board.moved()) == 2)

    board.put(task("TASK-1", "Waiting", dependencies=("TASK-9",)))  # the operator returns it to Waiting
    assert until(lambda: _sample(actor.exposition(), "starpulse_task_actor_refusals_total") == 2)

    assert board.moved()[2:] == [("TASK-1", "ready")]
    assert [lane for _, lane in board.moved()].count("needs_attention") == 1


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


def test_a_criterion_in_error_for_two_passes_re_gates_the_task_once_without_parking_it(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(roles=ROLES), task("TASK-1", "Waiting", description=GATED))
    evaluate = Criteria("error")

    running(board, store, stop, evaluate=evaluate, fresh_s=0.05)

    assert until(lambda: evaluate.asked["TASK-1"] >= 3)
    assert [title for title, _ in board.created] == [
        "Re-gate TASK-1: re-park it on Start Criteria that can be evaluated"
    ]
    comments = [text for name, text in board.comments() if name == "TASK-1"]
    assert len(comments) == 1
    assert comments[0].startswith(REGATE)
    assert "cannot reach prometheus" in comments[0]
    assert board.moved() == [("TASK-101", "ready")]
    assert not any(name == "TASK-1" for name, _ in board.moved())
    assert board.created[0][1]["priority"] == "medium"  # the board holds none for TASK-1: the fallback
    assert board.created[0][1]["type"] == "chore"  # the board refuses a task with no type


def test_the_re_gate_task_carries_the_priority_of_the_task_it_unblocks(
    store: PullStore, stop: threading.Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = BoardFeed(roles=ROLES)
    board = Board(feed, task("TASK-1", "Waiting", description=GATED))
    held = feed.task
    monkeypatch.setattr(feed, "task", lambda name: {**(held(name) or {}), "priority": "high"})

    running(board, store, stop, evaluate=Criteria("error"), fresh_s=0.05)

    assert until(lambda: bool(board.created))
    assert board.created[0][1]["priority"] == "high"


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


def test_a_waiting_task_with_no_dependencies_and_no_start_criteria_is_released(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(roles=ROLES), task("TASK-1", "Waiting"))
    running(board, store, stop)

    assert until(lambda: board.moved() == [("TASK-1", "ready")])


def test_a_waiting_task_whose_start_criteria_pass_stays_waiting_while_a_dependency_is_open(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(roles=ROLES),
        task("TASK-9", "Ready"),
        task("TASK-1", "Waiting", description=GATED, dependencies=("TASK-9",)),
    )
    running(board, store, stop, evaluate=Criteria("met"))

    assert not until(lambda: board.moved(), within=0.3)


LINT = "a fast kind-execute task names no mechanism"


def test_a_release_the_task_lint_refuses_stays_in_waiting_with_the_lint_reason_and_no_operator_question(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(roles=ROLES), task("TASK-9", "Done"), task("TASK-1", "Waiting", dependencies=("TASK-9",)))
    board.linting["ready"] = LINT
    actor = running(board, store, stop)

    assert until(lambda: len(board.writes) == 2)
    assert board.moved() == [("TASK-1", "ready")]  # no move into Needs attention
    assert all("description" not in changes for _, changes, _, _ in board.writes)  # no operator question written
    assert board.comments() == [("TASK-1", f"{LINT_REFUSED} {LINT}.")]
    assert _sample(actor.exposition(), "starpulse_task_actor_refusals_total") == 1


def test_a_lint_refused_task_is_released_when_its_record_is_repaired(store: PullStore, stop: threading.Event) -> None:
    board = Board(BoardFeed(roles=ROLES), task("TASK-9", "Done"), task("TASK-1", "Waiting", dependencies=("TASK-9",)))
    board.linting["ready"] = LINT
    running(board, store, stop)
    assert until(lambda: len(board.writes) == 2)

    board.linting.clear()
    board.put(task("TASK-1", "Waiting", dependencies=("TASK-9",), description="Mechanism: x, checked against a.py:1"))

    assert until(lambda: board.moved() == [("TASK-1", "ready"), ("TASK-1", "ready")])
    assert len(board.comments()) == 1


def test_an_unrelated_change_to_a_lint_refused_task_does_not_try_its_release_again(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(roles=ROLES), task("TASK-9", "Done"), task("TASK-1", "Waiting", dependencies=("TASK-9",)))
    board.linting["ready"] = LINT
    running(board, store, stop)
    assert until(lambda: len(board.writes) == 2)

    board.put(task("TASK-1", "Waiting", dependencies=("TASK-9",)))

    assert not until(lambda: len(board.writes) > 2, within=0.5)


def test_a_waiting_task_whose_return_to_review_is_refused_moves_to_ready_when_its_last_dependency_is_done(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(roles=ROLES),
        task("TASK-8", "Ready"),
        task("TASK-9", "Ready"),
        task("TASK-1", "Waiting", references=(PR_ONE,), dependencies=("TASK-8", "TASK-9")),
    )
    board.refusing["review"] = "Review needs every Acceptance Criterion checked"
    store.save([pull(1, state="OPEN")])
    running(board, store, stop)

    board.put(task("TASK-8", "Done"))
    board.put(task("TASK-9", "Done"))

    assert until(lambda: ("TASK-1", "ready") in board.moved())


def test_a_red_check_demotes_a_review_task_to_needs_attention_with_the_failure_and_the_question(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(roles=ROLES), task("TASK-1", "Review", references=(PR_ONE,)))
    store.save([pull(1, state="OPEN", checks="failing")])

    running(board, store, stop)

    assert until(lambda: board.moved() == [("TASK-1", "needs_attention")])
    _, changes, comment, actor = board.writes[0]
    assert actor == ACTOR
    assert comment == f"Pull request checks failed: acme/trantor#1 at {HEAD}. {ATTENTION_QUESTION}"
    assert changes["description"].endswith(f"## Needs attention\n\n{comment}")


@pytest.mark.parametrize(
    ("option", "said"),
    [
        ({"mergeable": "CONFLICTING"}, "Pull request conflicts with its base"),
        ({"draft": True}, "Pull request is a draft"),
    ],
)
def test_a_conflicting_or_draft_pull_request_sends_a_review_task_back_and_hands_it_to_the_returned_hook(
    store: PullStore, stop: threading.Event, option: dict, said: str
) -> None:
    returned: list[str] = []
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(PR_ONE,)))
    board.refusing["review"] = "Pull request is not green"  # the board's guard, which keeps it from bouncing back
    store.save([pull(1, state="OPEN", **option)])

    running(board, store, stop, returned=returned.append)

    assert until(lambda: board.moved()[:1] == [("TASK-1", "in_progress")])
    assert board.writes[0][2] == f"{said}: acme/trantor#1 at {HEAD}."
    assert until(lambda: returned == ["TASK-1"])
    assert board.tasks["TASK-1"].lane == "in_progress"


def test_a_merged_pull_request_closes_a_review_task_whose_checks_failed_and_a_green_one_stays_in_review(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(roles=ROLES),
        task("TASK-1", "Review", references=(PR_ONE,)),
        task("TASK-2", "Review", references=(PR_TWO,)),
    )
    store.save([pull(1, state="MERGED", checks="failing"), pull(2, state="OPEN")])

    running(board, store, stop)

    assert until(lambda: board.moved() == [("TASK-1", "done")])
    assert not until(lambda: len(board.moved()) > 1, within=0.3)
