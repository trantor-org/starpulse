"""The task actor moves a task on the facts its lane waits on, as `starpulse/task-actor`, through the board's editor."""

import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine
from starpulse.board.board_feed import BoardFeed
from starpulse.board.machine_tasks import MachineTasks
from starpulse.contracts.adapters import BoardTask, MachineEvent
from starpulse.event_log.event_log import Entry, EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.machine_engine.adapters.machine_loader import load_machine
from starpulse.machine_engine.model.snapshot import describe
from starpulse.machine_engine.model.transitions import board_machine
from starpulse.pulls.adapters.inbound import task_actor
from starpulse.pulls.adapters.inbound.task_actor import ACTOR, TaskActor
from starpulse.pulls.adapters.outbound.pull_events import RecordProjection
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.runtime import server
from starpulse.runtime.adapter_kit import task
from starpulse.runtime.assembly import assemble
from starpulse.runtime.config import load

from tests.machines import MACHINES, ROLES, STATUSES
from tests.task_actor_kit import (
    CHILD,
    CHILD_PR,
    GATED,
    MOVES,
    PARENT,
    PR_ONE,
    PR_THREE,
    PR_TWO,
    REPOS,
    SHA,
    WAITS,
    WITHIN_S,
    Board,
    Criteria,
    Pins,
    pull,
    running,
    until,
)


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = threading.Event()
    yield event
    event.set()


def test_a_review_task_whose_only_pr_merged_moves_to_done_and_no_other_task_is_derived(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Review", references=(PR_ONE,)),
        task("TASK-2", "Review", references=(PR_TWO,)),
        task("TASK-3", "Ready"),
    )
    store.save([pull(1, state="OPEN"), pull(2, state="OPEN")])
    actor = running(board, store, stop)
    derived = dict(actor.derivations)
    store.save([pull(1, state="MERGED")])

    projected = time.monotonic()
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "done")])
    assert time.monotonic() - projected < WITHIN_S
    name, changes, comment, actor_name = board.writes[0]
    assert (changes, actor_name) == ({"status": "done"}, ACTOR)
    assert f"acme/trantor#1 merged as {SHA}" in str(comment)
    assert {name: count - derived[name] for name, count in actor.derivations.items()} == {
        "TASK-1": 1,
        "TASK-2": 0,
        "TASK-3": 0,
    }


def test_a_merge_routes_on_verify_plan_a_planned_review_task_to_in_progress_and_an_unplanned_one_to_done(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Review", references=(PR_ONE,)),
        task("TASK-2", "Review", references=(PR_TWO,)),
        task("TASK-3", "Review", references=(PR_THREE,)),
    )
    plans = {"TASK-1": ["make check"], "TASK-2": [], "TASK-3": ["make check"]}
    waits = {**WAITS, "review": {"pr_merged_planned": "MERGED_VERIFY", "pr_merged": "MERGED"}}
    moves = {**MOVES, ("review", "MERGED_VERIFY"): "in_progress"}
    store.save([pull(1, state="OPEN"), pull(2, state="OPEN"), pull(3, state="OPEN")])
    actor = running(board, store, stop, waits, moves, read=lambda name: {"verifyPlan": plans[name]})
    store.save([pull(1, state="MERGED"), pull(2, state="MERGED"), pull(3, state="CLOSED")])

    actor.pulls_changed()

    assert until(lambda: sorted(board.moved()) == [("TASK-1", "in_progress"), ("TASK-2", "done")])
    assert all(name != "TASK-3" for name, *_ in board.writes)  # closed unmerged: neither route


def test_a_review_task_whose_every_pr_closed_unmerged_moves_to_needs_attention_with_a_question_and_a_merged_one_closes(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Review", references=(PR_ONE,)),
        task("TASK-2", "Review", references=(PR_TWO, PR_THREE)),
    )
    waits = {**WAITS, "review": {"pr_merged": "MERGED", "pr_closed_unmerged": "ABANDONED"}}
    moves = {**MOVES, ("review", "ABANDONED"): "needs_attention"}
    store.save([pull(1, state="OPEN"), pull(2, state="OPEN"), pull(3, state="OPEN")])
    actor = running(board, store, stop, waits, moves)
    store.save([pull(1, state="CLOSED"), pull(2, state="CLOSED"), pull(3, state="MERGED")])

    actor.pulls_changed()

    assert until(lambda: sorted(board.moved()) == [("TASK-1", "needs_attention"), ("TASK-2", "done")])
    (_, changes, _, writer) = next(write for write in board.writes if write[0] == "TASK-1")
    reason = changes["description"]
    assert writer == ACTOR
    assert "## Needs attention" in reason
    assert PR_ONE in reason
    assert reason.rstrip().endswith("?")


def test_a_review_task_with_every_criterion_checked_whose_every_pr_closed_unmerged_closes_done(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Review", references=(PR_ONE,), acceptance_criteria=("a", "b"), acceptance_checked=(True, True)),
        task("TASK-2", "Review", references=(PR_TWO,), acceptance_criteria=("a", "b"), acceptance_checked=(True, False)),
    )
    waits = {**WAITS, "review": {"pr_merged": "MERGED", "pr_closed_unmerged_complete": "CLOSED_COMPLETE"}}
    moves = {**MOVES, ("review", "CLOSED_COMPLETE"): "done"}
    store.save([pull(1, state="OPEN"), pull(2, state="OPEN")])
    actor = running(board, store, stop, waits, moves)
    store.save([pull(1, state="CLOSED"), pull(2, state="CLOSED")])

    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "done")])
    assert all(name == "TASK-1" for name, *_ in board.writes)  # an unchecked criterion leaves the delivery open


def test_a_review_task_citing_only_another_tasks_merged_pr_closes_and_one_citing_its_own_closes(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Review", references=(PR_ONE,)),
        task("TASK-2", "Review", references=(PR_TWO,)),
        task("TASK-3", "Review", references=(PR_THREE,)),
    )
    store.save([pull(1, state="OPEN"), pull(2, state="OPEN"), pull(3, state="OPEN")])
    actor = running(board, store, stop)
    store.save(
        [
            pull(1, state="MERGED", branch="claude/task-9-other"),
            pull(2, state="MERGED", branch="claude/task-2-own"),
            pull(3, state="MERGED", title="fix(TASK-3): own"),
        ]
    )

    actor.pulls_changed()

    assert until(lambda: sorted(board.moved()) == [("TASK-1", "done"), ("TASK-2", "done"), ("TASK-3", "done")])
    assert [name for name, _ in board.comments()] == []


def test_a_review_check_task_citing_only_other_tasks_prs_closes_and_a_feature_task_doing_so_stays(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Review", type="check", references=(PR_ONE,)),
        task("TASK-2", "Review", type="check", references=(PR_TWO, PR_THREE)),
        task("TASK-3", "Ready", type="story", references=(PR_ONE,)),
    )
    store.save([pull(1, state="OPEN", branch="claude/task-9-other"), pull(2, state="OPEN"), pull(3, state="OPEN")])
    actor = running(board, store, stop)
    store.save(
        [
            pull(1, state="MERGED", branch="claude/task-9-other"),
            pull(2, state="OPEN", branch="claude/task-2-own"),
            pull(3, state="MERGED", branch="claude/task-8-other"),
        ]
    )

    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "done")])
    assert "no pull request of its own; cites " + PR_ONE in str(board.writes[0][2])
    assert all(name == "TASK-1" for name, *_ in board.writes)


def test_a_review_task_whose_own_pr_closed_unmerged_and_superseded_by_another_tasks_merged_pr_closes(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(PR_ONE, PR_TWO)))
    store.save([pull(1, state="OPEN", branch="claude/task-1-own"), pull(2, state="OPEN", branch="claude/task-9-other")])
    actor = running(board, store, stop)
    store.save(
        [
            pull(1, state="CLOSED", branch="claude/task-1-own"),
            pull(2, state="MERGED", branch="claude/task-9-other"),
        ]
    )

    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "done")])
    assert PR_TWO in str(board.writes[0][2])


def test_a_ready_or_in_progress_task_citing_another_tasks_merged_pr_derives_nothing(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Ready", references=(PR_ONE,)),
        task("TASK-2", "In Progress", references=(PR_TWO,)),
    )
    store.save(
        [pull(1, state="OPEN", branch="claude/task-9-other"), pull(2, state="OPEN", branch="claude/task-8-other")]
    )
    actor = running(board, store, stop)
    store.save(
        [
            pull(1, state="MERGED", branch="claude/task-9-other"),
            pull(2, state="MERGED", branch="claude/task-8-other"),
        ]
    )

    actor.pulls_changed()

    assert board.moved() == []
    assert board.writes == []


def test_a_needs_attention_task_closes_once_every_pr_ended_and_one_merged_but_not_when_all_closed(
    store: PullStore, stop: threading.Event
) -> None:
    waits = {**WAITS, "needs_attention": {"pr_merged": "MERGED"}}
    moves = {**MOVES, ("needs_attention", "MERGED"): "done"}
    board = Board(
        BoardFeed(),
        task("TASK-1", "Needs attention", references=(PR_ONE,)),
        task("TASK-2", "Needs attention", references=(PR_TWO,)),
        task("TASK-3", "Needs attention", references=(PR_ONE, PR_TWO)),
    )
    store.save([pull(1, state="OPEN"), pull(2, state="CLOSED")])
    actor = TaskActor(board.feed, store, board.edit, waits, moves)
    actor.start(stop)
    assert actor.ready.wait(WITHIN_S)
    assert board.moved() == []

    store.save([pull(1, state="MERGED")])
    actor.pulls_changed()

    assert until(lambda: sorted(board.moved()) == [("TASK-1", "done"), ("TASK-3", "done")])
    assert all(actor_name == ACTOR for _, _, _, actor_name in board.writes)
    assert f"acme/trantor#1 merged as {SHA}" in str(board.writes[0][2])


def test_a_needs_attention_task_whose_pr_merged_with_work_unfinished_returns_to_ready_and_one_without_closes(
    store: PullStore, stop: threading.Event
) -> None:
    waits = {**WAITS, "needs_attention": {"pr_merged_unfinished": "MERGED_UNFINISHED", "pr_merged": "MERGED"}}
    moves = {**MOVES, ("needs_attention", "MERGED"): "done", ("needs_attention", "MERGED_UNFINISHED"): "ready"}
    unfinished = {
        "TASK-1": ["acme/starpulse has no merged pull request"],
        "TASK-2": [],
        "TASK-3": ["criterion #2 open"],
    }
    board = Board(
        BoardFeed(),
        task("TASK-1", "Needs attention", references=(PR_ONE,)),
        task("TASK-2", "Needs attention", references=(PR_TWO,)),
        task("TASK-3", "Needs attention", references=(PR_THREE,)),
    )
    store.save([pull(1, state="OPEN"), pull(2, state="OPEN"), pull(3, state="OPEN")])
    actor = running(board, store, stop, waits, moves, unfinished=lambda name: unfinished[name])
    assert board.moved() == []

    store.save([pull(1, state="MERGED"), pull(2, state="MERGED"), pull(3, state="CLOSED")])
    actor.pulls_changed()

    assert until(lambda: sorted(board.moved()) == [("TASK-1", "ready"), ("TASK-2", "done")])
    assert "acme/starpulse has no merged pull request" in str(board.writes[0][2])


def test_a_needs_attention_task_returns_to_ready_with_the_error_when_the_unfinished_command_fails(
    store: PullStore, stop: threading.Event
) -> None:
    waits = {**WAITS, "needs_attention": {"pr_merged_unfinished": "MERGED_UNFINISHED", "pr_merged": "MERGED"}}
    moves = {**MOVES, ("needs_attention", "MERGED"): "done", ("needs_attention", "MERGED_UNFINISHED"): "ready"}

    def broken(name: str) -> list[str]:
        raise ValueError("unfinished printed nothing")

    board = Board(BoardFeed(), task("TASK-1", "Needs attention", references=(PR_ONE,)))
    store.save([pull(1, state="OPEN")])
    actor = running(board, store, stop, waits, moves, unfinished=broken)

    store.save([pull(1, state="MERGED")])
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "ready")])
    assert "unfinished printed nothing" in str(board.writes[0][2])


def test_a_closing_comment_for_a_pull_request_in_another_repo_links_that_repos_pull_url(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(CHILD_PR,)))
    store.save([pull(10, state="OPEN", repo="acme/starpulse")])
    actor = running(board, store, stop)
    store.save([pull(10, state="MERGED", repo="acme/starpulse")])

    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "done")])
    _, _, comment, _ = board.writes[0]
    assert f"({CHILD_PR})" in str(comment)
    assert "(PR #10)" not in str(comment)


def test_an_in_progress_task_citing_a_ready_or_merged_pull_request_moves_to_review_once(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "In Progress", references=(PR_ONE,)),
        task("TASK-2", "In Progress", references=(PR_TWO,)),
    )
    store.save([pull(1, state="OPEN"), pull(2, state="MERGED")])

    actor = running(board, store, stop)

    assert until(lambda: board.moved() == [("TASK-1", "review"), ("TASK-2", "review"), ("TASK-2", "done")])
    actor.pulls_changed()
    assert len(board.writes) == 3
    assert "acme/trantor#1 ready" in str(board.writes[0][2])
    assert "acme/trantor#2 merged" in str(board.writes[1][2])


def test_an_in_progress_task_citing_only_a_draft_or_closed_pull_request_stays(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "In Progress", references=(PR_ONE,)),
        task("TASK-2", "In Progress", references=(PR_TWO,)),
        task("TASK-3", "In Progress"),
    )
    draft = pull(1, state="OPEN") | {"isDraft": True}
    store.save([draft, pull(2, state="CLOSED")])
    actor = running(board, store, stop)

    actor.pulls_changed()

    assert board.moved() == []

    store.save([pull(1, state="OPEN")])  # the draft is marked ready: only isDraft changed
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "review")])


def test_a_review_task_sent_back_to_in_progress_stays_while_its_pull_request_keeps_the_head_it_was_sent_back_on(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(PR_ONE,)))
    store.save([pull(1, state="OPEN")])
    actor = running(board, store, stop)
    seen = actor.derivations["TASK-1"]

    board.put(task("TASK-1", "In Progress", references=(PR_ONE,)))  # the operator's drag
    assert until(lambda: actor.derivations["TASK-1"] > seen)
    actor.pulls_changed()

    assert board.moved() == []

    store.save([pull(1, state="OPEN") | {"headRefOid": "a" * 40}])  # the session pushes its rework
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "review")])


def test_a_waiting_task_moves_to_ready_when_its_last_dependency_enters_done(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Done"),
        task("TASK-2", "In Progress"),
        task("TASK-3", "Waiting", dependencies=("TASK-1", "TASK-2")),
    )
    running(board, store, stop)
    assert board.moved() == []

    board.put(task("TASK-2", "Done"))

    assert until(lambda: board.moved() == [("TASK-3", "ready")])
    assert board.writes[0][3] == ACTOR


def test_a_review_task_stays_while_its_parent_pr_is_open_after_its_child_pr_closes(
    store: PullStore, stop: threading.Event
) -> None:
    feed = BoardFeed()
    board = Board(feed, task("TASK-1", "Review", references=(PR_ONE, PR_TWO)))
    store.save([pull(1, state="OPEN"), pull(2, state="CLOSED")])  # a poll read the child closed before the event
    actor = running(board, store, stop)
    event = {"event_id": "e1", "machine": "github-pull-request", "event": "PR_CLOSED", "task": "TASK-1"}
    event |= {"time": str(time.time() + 60), "repository": "acme/trantor", "pr": "2"}

    RecordProjection(store, feed).handle(Entry(1, "machine:events", "e1", event, time.time()))
    actor.pulls_changed()

    assert [record["state"] for record in store.find(repo="acme/trantor", number=1)] == ["OPEN"]
    assert board.moved() == []


def test_a_ready_task_with_an_unresolved_dependency_moves_to_waiting(store: PullStore, stop: threading.Event) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "In Progress"),
        task("TASK-2", "Ready", dependencies=("TASK-1",)),
        task("TASK-3", "Ready"),
    )

    running(board, store, stop)

    assert until(lambda: board.moved() == [("TASK-2", "waiting")])


def test_a_pin_bump_rule_holds_the_dependent_until_the_pin_bump_merge_projects(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Done", references=(CHILD_PR,)),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
    )
    store.save([pull(10, state="MERGED", repo="acme/starpulse", sha=CHILD)])
    actor = running(board, store, stop, repos=REPOS, pin_rule="pin-bump", pins=Pins())
    assert board.moved() == []
    assert "\nstarpulse_task_actor_pin_held 1\n" in actor.exposition()

    store.save([pull(11, state="MERGED", sha=PARENT, files=("starpulse",))])
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-2", "ready")])
    assert "\nstarpulse_task_actor_pin_held 0\n" in actor.exposition()


def test_a_pin_hold_comments_the_pull_request_and_pin_it_waits_on_once(store: PullStore, stop: threading.Event) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Done", references=(CHILD_PR,)),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
    )
    store.save([pull(10, state="MERGED", repo="acme/starpulse", sha=CHILD)])
    actor = running(board, store, stop, repos=REPOS, pin_rule="pin-bump", pins=Pins())
    assert board.moved() == []
    assert board.comments() == [
        ("TASK-2", f"Held from Ready: {CHILD_PR} is merged but no merged bump pins it at starpulse yet.")
    ]

    store.save([pull(11, state="MERGED", sha=PARENT, files=("starpulse",))])
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-2", "ready")])
    assert len(board.comments()) == 1


def test_a_gated_task_is_released_while_another_tasks_evaluation_is_still_running(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Waiting", description=GATED), task("TASK-2", "Waiting", description=GATED))
    answer = Criteria("met")
    hung = threading.Event()

    def evaluate(name: str, description: str) -> list[dict[str, Any]]:
        if name == "TASK-1":  # a prom query that has not answered; TASK-2 sorts after it
            hung.wait(5)
        return answer(name, description)

    try:
        running(board, store, stop, evaluate=evaluate)

        assert until(lambda: ("TASK-2", "ready") in board.moved())
        assert ("TASK-1", "ready") not in board.moved()
    finally:
        hung.set()


def test_a_task_parked_again_on_new_criteria_is_not_released_on_the_result_of_its_last_park(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Waiting", description=GATED),
        task("TASK-2", "Waiting", description=GATED.replace("soak", "slow")),
    )
    hung = threading.Event()
    met, unmet = Criteria("met"), Criteria("unmet")

    def evaluate(name: str, description: str) -> list[dict[str, Any]]:
        if name == "TASK-2":  # a slow evaluation holds the pass, so its sweep of finished tasks does not run
            hung.wait(5)
        return (met if "soak" in description else unmet)(name, description)  # only the first park's criterion is met

    try:
        running(board, store, stop, evaluate=evaluate, fresh_s=0.05)
        assert until(lambda: board.moved()[:1] == [("TASK-1", "ready")] and board.tasks["TASK-1"].lane == "ready")
        until(lambda: False, within=0.2)  # the first release's own re-derivation lands before the task is parked again
        released = len(board.moved())

        board.put(task("TASK-1", "In Progress", description=GATED))
        board.put(task("TASK-1", "Waiting", description=GATED.replace("soak", "merged")))

        assert not until(lambda: len(board.moved()) > released, within=0.3)
    finally:
        hung.set()


def test_a_review_task_whose_pr_merged_while_the_server_was_down_moves_on_start(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(PR_ONE,)), task("TASK-2", "Review"))
    store.save([pull(1, state="MERGED")])

    actor = running(board, store, stop)

    assert board.moved() == [("TASK-1", "done")]
    assert actor.derivations["TASK-2"] == 1  # every open task is derived once on start


def test_criteria_move_a_gated_task_both_ways_each_time_the_evaluators_result_goes_stale(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Waiting", description=GATED), task("TASK-2", "Waiting"))
    evaluate = Criteria("unmet")
    running(board, store, stop, evaluate=evaluate, fresh_s=0.05)
    assert (
        "TASK-1",
        "ready",
    ) not in board.moved()  # the second task has no criteria and no dependency: released at once

    evaluate.status = "met"

    assert until(lambda: ("TASK-1", "ready") in board.moved())
    assert {each[3] for each in board.writes} == {ACTOR}
    evaluate.status = "unmet"
    assert until(
        lambda: [each for each in board.moved() if each[0] == "TASK-1"] == [("TASK-1", "ready"), ("TASK-1", "waiting")]
    )
    assert "TASK-2" not in evaluate.asked  # a task with no Start Criteria is never evaluated


def test_an_adapter_hold_withholds_deps_done_with_its_reason_until_a_task_is_created(
    store: PullStore, stop: threading.Event
) -> None:
    held = {"TASK-2": ['"Slice three" has no task']}
    board = Board(BoardFeed(), task("TASK-1", "Done"), task("TASK-2", "Waiting", dependencies=("TASK-1",)))
    running(board, store, stop, holds=lambda name: held.get(name, []))
    assert board.moved() == []
    assert board.comments() == [("TASK-2", 'Held from Ready: "Slice three" has no task.')]

    held.clear()
    board.put(task("TASK-3", "Ready", title="Slice three"))

    assert until(lambda: board.moved() == [("TASK-2", "ready")])
    assert len(board.comments()) == 1  # the reason is written once, not on every derivation


def test_a_restarted_actor_does_not_write_the_hold_comment_the_task_already_holds(
    store: PullStore, stop: threading.Event, tmp_path: Path
) -> None:
    tasks = tmp_path / ".starpulse" / "board" / "tasks"
    tasks.mkdir(parents=True)
    (tasks.parent / "config.yml").write_text("project_name: Trantor\n")
    path = tasks / "task-2 - Held.md"
    path.write_text(
        "---\nid: task-2\ntitle: Held\nstatus: Waiting\ndependencies:\n  - task-1\n---\n\n## Description\n\nHeld.\n"
    )
    edit = assemble(load(None), tmp_path, None, ())[0].edit
    reason = ['"Slice three" has no task']

    for _ in range(2):  # the second pass is the restart: a new actor, an empty in-memory memo
        board = Board(BoardFeed(), task("task-1", "Done"), task("task-2", "Waiting", dependencies=("task-1",)))
        actor = TaskActor(board.feed, store, edit, WAITS, MOVES, holds=lambda name: reason)
        actor.start(stop)
        assert actor.ready.wait(WITHIN_S)

    assert path.read_text().count('Held from Ready: "Slice three" has no task.') == 1


class _BlockedProjection:
    """`PullRequests` whose refresh is a pin walk that has not returned."""

    release = threading.Event()

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def refresh(self) -> None:
        self.release.wait(WITHIN_S * 10)


class _Sync:
    projects: list[Callable[[], None]] = []

    def __init__(self, *args: object, project: Callable[[], None], **kwargs: object) -> None:
        self.projects.append(project)

    def run_forever(self) -> None:
        pass


def test_a_store_save_moves_the_task_while_the_projection_is_still_blocked(
    store: PullStore, stop: threading.Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    board = Board(feed, task("TASK-1", "Review", references=(PR_ONE,)))
    store.save([pull(1, state="OPEN")])
    delivery = SimpleNamespace(
        edit=board.edit,
        waits=WAITS,
        evaluate=None,
        holds=None,
        read=None,
        unfinished=None,
        create=None,
        parked=None,
        sent_back=None,
        closed=None,
        released=None,
        delivered=None,
    )
    monkeypatch.setattr(server.shutil, "which", lambda name: name)
    monkeypatch.setattr(server, "moves_of", lambda machine: MOVES)
    monkeypatch.setattr(server, "PullRequests", _BlockedProjection)
    monkeypatch.setattr(server, "PullSync", _Sync)
    monkeypatch.setattr(_Sync, "projects", [])
    monkeypatch.setattr(_BlockedProjection, "release", threading.Event())
    actor, _ = server.start_delivery(replace(load(None), task_actor=True), delivery, feed, None, store, Pins(), stop)
    assert actor.ready.wait(WITHIN_S)
    projection = threading.Thread(target=_Sync.projects[0], daemon=True)
    projection.start()

    store.save([pull(1, state="MERGED")])

    moved = until(lambda: board.moved() == [("TASK-1", "done")])
    still_projecting = projection.is_alive()
    _BlockedProjection.release.set()
    assert (moved, still_projecting) == (True, True)


def test_a_merge_of_a_pr_added_after_startup_moves_the_task_to_done(
    tmp_path: Path, store: PullStore, stop: threading.Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine
    events = EventStore(engine)
    created = NewEvent(
        type="TaskCreated", payload={"title": "Task", "state": "Review"}, actor="adin", writer="operator"
    )
    events.append("task", "TASK-1", 0, [created])
    Projector(engine, events).catch_up()
    feed = BoardFeed(roles=ROLES, machines=MACHINES, read_model=ReadModel(engine))
    board = Board(feed)
    store.save([pull(1, state="OPEN")])
    delivery = SimpleNamespace(
        edit=board.edit,
        waits=WAITS,
        evaluate=None,
        holds=None,
        read=None,
        unfinished=None,
        create=None,
        parked=None,
        sent_back=None,
        closed=None,
        released=None,
        delivered=None,
    )
    monkeypatch.setattr(server.shutil, "which", lambda name: name)
    monkeypatch.setattr(server, "moves_of", lambda machine: MOVES)
    monkeypatch.setattr(server, "PullRequests", _BlockedProjection)
    monkeypatch.setattr(server, "PullSync", _Sync)
    monkeypatch.setattr(_Sync, "projects", [])
    monkeypatch.setattr(_BlockedProjection, "release", threading.Event())
    actor, _ = server.start_delivery(replace(load(None), task_actor=True), delivery, feed, None, store, Pins(), stop)
    assert actor.ready.wait(WITHIN_S)
    projection = threading.Thread(target=_Sync.projects[0], daemon=True)
    projection.start()

    referenced = NewEvent(
        type="FieldsEdited", payload={"changes": {"references": [PR_ONE]}}, actor="adin", writer="operator"
    )
    events.append("task", "TASK-1", 1, [referenced])
    Projector(engine, events).catch_up()
    feed.follow_read_model()  # the page's follow publishes the changed task to the actor, as the server does
    store.save([pull(1, state="MERGED")])

    moved = until(lambda: board.moved() == [("TASK-1", "done")], within=WITHIN_S * 10)
    still_projecting = projection.is_alive()
    _BlockedProjection.release.set()
    assert (moved, still_projecting) == (True, True)


def test_a_read_model_task_whose_cited_pr_merged_before_startup_moves_to_done(
    tmp_path: Path, store: PullStore, stop: threading.Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine
    events = EventStore(engine)
    created = NewEvent(
        type="TaskCreated", payload={"title": "Task", "state": "Review"}, actor="adin", writer="operator"
    )
    referenced = NewEvent(
        type="FieldsEdited", payload={"changes": {"references": [PR_ONE]}}, actor="adin", writer="operator"
    )
    events.append("task", "TASK-1", 0, [created, referenced])
    Projector(engine, events).catch_up()
    feed = BoardFeed(roles=ROLES, machines=MACHINES, read_model=ReadModel(engine))
    board = Board(feed)
    store.save([pull(1, state="MERGED")])
    delivery = SimpleNamespace(
        edit=board.edit,
        waits=WAITS,
        evaluate=None,
        holds=None,
        read=None,
        unfinished=None,
        create=None,
        parked=None,
        sent_back=None,
        closed=None,
        released=None,
        delivered=None,
    )
    monkeypatch.setattr(server.shutil, "which", lambda name: name)
    monkeypatch.setattr(server, "moves_of", lambda machine: MOVES)
    monkeypatch.setattr(server, "PullRequests", _BlockedProjection)
    monkeypatch.setattr(server, "PullSync", _Sync)
    monkeypatch.setattr(_Sync, "projects", [])
    monkeypatch.setattr(_BlockedProjection, "release", threading.Event())
    _BlockedProjection.release.set()
    server.start_delivery(replace(load(None), task_actor=True), delivery, feed, None, store, Pins(), stop)

    assert until(lambda: board.moved() == [("TASK-1", "done")])


def test_a_review_task_with_an_open_child_pr_stays_open_when_its_other_pr_merged(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(PR_ONE, CHILD_PR)))
    store.save([pull(1, state="MERGED"), pull(10, state="OPEN", repo="acme/starpulse")])

    actor = running(board, store, stop)
    actor.pulls_changed()

    assert not until(lambda: board.moved() != [], within=0.3)


def test_a_review_task_whose_pr_is_merged_with_no_merge_time_stays_open(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(PR_ONE,)))
    unproven = pull(1, state="MERGED") | {"mergedAt": None, "mergeSha": None}
    store.save([unproven])

    actor = running(board, store, stop)
    actor.pulls_changed()

    assert not until(lambda: board.moved() != [], within=0.3)


#: The lanes that park on an open dependency, and the return a task with a delivery takes: Review rather than Ready.
PARKING_WAITS = {
    **WAITS,
    "in_progress": {"deps_unresolved": "WAIT_ON_DEPS"},
    "review": {"pr_terminal": "MERGED", "deps_unresolved": "WAIT_ON_DEPS"},
    "waiting": {"deps_done_with_pr": "DEPS_DONE_REVIEW", "deps_done": "DEPS_DONE", "criteria_met": "CRITERIA_MET"},
}
PARKING_MOVES = {
    **MOVES,
    ("in_progress", "WAIT_ON_DEPS"): "waiting",
    ("review", "WAIT_ON_DEPS"): "waiting",
    ("waiting", "DEPS_DONE_REVIEW"): "review",
}


def test_a_review_task_given_an_open_dependency_waits_and_returns_to_review_when_it_is_done(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "In Progress"), task("TASK-2", "Review", references=(PR_ONE,)))
    store.save([pull(1, state="OPEN")])
    running(board, store, stop, PARKING_WAITS, PARKING_MOVES)

    board.put(task("TASK-2", "Review", references=(PR_ONE,), dependencies=("TASK-1",)))
    assert until(lambda: board.moved() == [("TASK-2", "waiting")])

    board.put(task("TASK-1", "Done"))
    assert until(lambda: board.moved() == [("TASK-2", "waiting"), ("TASK-2", "review")])


def test_a_waiting_task_without_a_pull_request_returns_to_ready_when_its_dependency_is_done(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "In Progress"), task("TASK-2", "Waiting", dependencies=("TASK-1",)))
    running(board, store, stop, PARKING_WAITS, PARKING_MOVES)

    board.put(task("TASK-1", "Done"))

    assert until(lambda: board.moved() == [("TASK-2", "ready")])


def test_an_in_progress_task_given_an_open_dependency_waits_and_its_holder_is_told(
    store: PullStore, stop: threading.Event
) -> None:
    told: list[str] = []
    board = Board(BoardFeed(roles=ROLES), task("TASK-1", "Ready"), task("TASK-2", "In Progress"))
    running(board, store, stop, PARKING_WAITS, PARKING_MOVES, parked=told.append)

    board.put(task("TASK-2", "In Progress", dependencies=("TASK-1",)))

    assert until(lambda: board.moved() == [("TASK-2", "waiting")])
    assert until(lambda: told == ["TASK-2"])


def test_a_review_task_given_an_open_dependency_tells_no_holder(store: PullStore, stop: threading.Event) -> None:
    told: list[str] = []
    board = Board(BoardFeed(roles=ROLES), task("TASK-1", "Ready"), task("TASK-2", "Review", references=(PR_ONE,)))
    store.save([pull(1, state="OPEN")])
    running(board, store, stop, PARKING_WAITS, PARKING_MOVES, parked=told.append)

    board.put(task("TASK-2", "Review", references=(PR_ONE,), dependencies=("TASK-1",)))

    assert until(lambda: board.moved() == [("TASK-2", "waiting")])
    assert told == []


def test_a_task_the_actor_closes_is_handed_to_the_closed_hook(store: PullStore, stop: threading.Event) -> None:
    closed: list[str] = []
    board = Board(BoardFeed(roles=ROLES), task("TASK-1", "Review", references=(PR_ONE,)))
    store.save([pull(1, state="OPEN")])
    actor = running(board, store, stop, closed=closed.append)

    store.save([pull(1, state="MERGED")])
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "done")])
    assert until(lambda: closed == ["TASK-1"])


def test_a_closed_hook_that_raises_leaves_the_task_done(store: PullStore, stop: threading.Event) -> None:
    def closed(task: str) -> None:
        raise ValueError("no checkup filed")

    board = Board(BoardFeed(roles=ROLES), task("TASK-1", "Review", references=(PR_ONE,)))
    store.save([pull(1, state="OPEN")])
    actor = running(board, store, stop, closed=closed)

    store.save([pull(1, state="MERGED")])
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "done")])


def test_a_task_parked_on_a_dependency_is_handed_to_the_released_hook_once_it_returns_to_ready(
    store: PullStore, stop: threading.Event
) -> None:
    released: list[str] = []
    board = Board(BoardFeed(roles=ROLES), task("TASK-1", "Ready"), task("TASK-2", "In Progress"))
    running(board, store, stop, PARKING_WAITS, PARKING_MOVES, released=released.append)
    board.put(task("TASK-2", "In Progress", dependencies=("TASK-1",)))
    assert until(lambda: board.moved() == [("TASK-2", "waiting")])
    assert released == []

    board.put(task("TASK-1", "Done"))

    assert until(lambda: board.moved() == [("TASK-2", "waiting"), ("TASK-2", "ready")])
    assert until(lambda: released == ["TASK-2"])


def test_a_released_hook_that_raises_leaves_the_task_ready(store: PullStore, stop: threading.Event) -> None:
    def released(task: str) -> None:
        raise ValueError("no session to wake")

    board = Board(
        BoardFeed(roles=ROLES), task("TASK-1", "In Progress"), task("TASK-2", "Waiting", dependencies=("TASK-1",))
    )
    running(board, store, stop, PARKING_WAITS, PARKING_MOVES, released=released)

    board.put(task("TASK-1", "Done"))

    assert until(lambda: board.moved() == [("TASK-2", "ready")])


def test_a_move_that_does_not_end_in_ready_calls_no_released_hook(store: PullStore, stop: threading.Event) -> None:
    released: list[str] = []
    board = Board(BoardFeed(roles=ROLES), task("TASK-1", "Ready"), task("TASK-2", "In Progress"))
    running(board, store, stop, PARKING_WAITS, PARKING_MOVES, released=released.append)

    board.put(task("TASK-2", "In Progress", dependencies=("TASK-1",)))

    assert until(lambda: board.moved() == [("TASK-2", "waiting")])
    assert released == []


MERGE_FIRST_WAITS = {**WAITS, "waiting": {"pr_merged": "MERGED", **WAITS["waiting"]}}
MERGE_FIRST_MOVES = {**MOVES, ("waiting", "MERGED"): "done"}


def test_a_waiting_task_whose_dependency_is_done_and_own_pr_merged_is_closed_not_released(
    store: PullStore, stop: threading.Event
) -> None:
    store.save([pull(1, state="MERGED")])
    board = Board(
        BoardFeed(), task("TASK-1", "Done"), task("TASK-2", "Waiting", references=(PR_ONE,), dependencies=("TASK-1",))
    )
    running(board, store, stop, MERGE_FIRST_WAITS, MERGE_FIRST_MOVES)

    assert until(lambda: board.moved() == [("TASK-2", "done")])
    assert "ready" not in [lane for _, lane in board.moved()]


def test_a_waiting_task_whose_criteria_are_met_and_own_pr_merged_is_closed_not_released(
    store: PullStore, stop: threading.Event
) -> None:
    store.save([pull(1, state="MERGED")])
    board = Board(BoardFeed(), task("TASK-1", "Waiting", description=GATED, references=(PR_ONE,)))
    running(board, store, stop, MERGE_FIRST_WAITS, MERGE_FIRST_MOVES, evaluate=Criteria("met"))

    assert until(lambda: board.moved() == [("TASK-1", "done")])
    assert "ready" not in [lane for _, lane in board.moved()]


def _owner(*checked: bool) -> BoardTask:
    """TASK-9550: an open task whose criterion #1 states the fact a dependent waits on and #2 the rest of its work."""
    return task(
        "TASK-9550",
        "In Progress",
        acceptance_criteria=("a worker claims a Validate run", "cap-4 claim within 5 minutes")[: len(checked)],
        acceptance_checked=checked,
    )


def _needing(*needs: str) -> Callable[[str], dict]:
    return lambda name: {"dependencyNeeds": list(needs)} if name == "TASK-2" else {}


def test_a_waiting_task_is_released_when_the_criterion_it_needs_of_an_open_dependency_is_checked(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), _owner(False, False), task("TASK-2", "Waiting", dependencies=("TASK-9550",)))
    running(board, store, stop, PARKING_WAITS, PARKING_MOVES, read=_needing("TASK-9550#1"))
    assert board.moved() == []

    board.put(_owner(True, False))

    assert until(lambda: board.moved() == [("TASK-2", "ready")])
    _, changes, comment, actor = board.writes[0]
    assert changes == {"status": "ready", "dependencies": [], "dependencyNeeds": []}
    assert "TASK-9550" in str(comment) and "stale" in str(comment).lower()
    assert actor == ACTOR


def test_a_waiting_task_stays_while_a_criterion_it_needs_is_open_or_it_names_none(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        _owner(False, True),
        task("TASK-2", "Waiting", dependencies=("TASK-9550",)),
        task("TASK-3", "Waiting", dependencies=("TASK-9550",)),
    )
    running(board, store, stop, PARKING_WAITS, PARKING_MOVES, read=_needing("TASK-9550#1"))

    board.put(_owner(False, True))  # a change of criteria that leaves #1 open
    board.put(task("TASK-3", "Waiting", dependencies=("TASK-9550",), title="touched"))

    time.sleep(0.2)
    assert board.moved() == []


def test_a_release_drops_only_the_dependencies_whose_needs_are_met(store: PullStore, stop: threading.Event) -> None:
    board = Board(
        BoardFeed(),
        _owner(True, False),
        task("TASK-1", "Done"),
        task("TASK-2", "Waiting", dependencies=("TASK-1", "TASK-9550")),
    )
    running(board, store, stop, PARKING_WAITS, PARKING_MOVES, read=_needing("TASK-9550#1"))

    assert until(lambda: board.moved() == [("TASK-2", "ready")])
    assert board.writes[0][1] == {"status": "ready", "dependencies": ["TASK-1"], "dependencyNeeds": []}


def test_a_dod_tick_that_leaves_a_merged_review_task_fully_checked_makes_the_done_move_the_guard_refused(
    tmp_path: Path, store: PullStore, stop: threading.Event
) -> None:
    engine = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine
    events = EventStore(engine)
    created = NewEvent(
        type="TaskCreated", payload={"title": "Task", "state": "Review"}, actor="adin", writer="operator"
    )
    referenced = NewEvent(
        type="FieldsEdited", payload={"changes": {"references": [PR_ONE]}}, actor="adin", writer="operator"
    )
    item = NewEvent(type="CriterionAdded", payload={"kind": "dod", "text": "Verify"}, actor="adin", writer="operator")
    events.append("task", "TASK-1", 0, [created, referenced, item])
    projector = Projector(engine, events)
    projector.catch_up()
    feed = BoardFeed(roles=ROLES, machines=MACHINES, read_model=ReadModel(engine))
    board = Board(feed)
    board.refusing["done"] = "Done needs every Definition of Done item checked"
    store.save([pull(1, state="MERGED")])
    running(board, store, stop)
    assert until(lambda: board.moved() == [("TASK-1", "done")])  # the merge's own attempt, refused

    board.refusing.clear()
    ticked = NewEvent(
        type="CriterionChecked", payload={"kind": "dod", "n": 1, "checked": True}, actor="adin", writer="operator"
    )
    events.append("task", "TASK-1", 3, [ticked])
    projector.catch_up()
    feed.follow_read_model()  # the page's follow publishes the changed task to the actor, as the server does

    assert until(lambda: board.moved() == [("TASK-1", "done")] * 2)


def test_a_review_task_whose_pr_merged_into_an_integration_branch_closes_only_once_that_branch_landed_on_main(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Review", references=(PR_ONE,)),
        task("TASK-2", "Review", references=(PR_TWO,)),
    )
    store.save([pull(1, state="OPEN"), pull(2, state="OPEN")])
    actor = running(board, store, stop)
    store.save(
        [
            pull(1, state="MERGED", base="agent/m-295-fixes"),
            pull(2, state="MERGED", base="agent/m-5-fixes"),
            pull(3, state="MERGED", branch="agent/m-5-fixes"),
        ]
    )

    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-2", "done")])
    assert [name for name, _ in board.comments()] == ["TASK-1"]  # the hold's comment, no move


def test_a_review_task_whose_pr_merged_into_a_non_default_base_is_held_out_of_done_naming_the_pr_once(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(PR_ONE,)))
    store.save([pull(1, state="OPEN")])
    actor = running(board, store, stop)
    store.save([pull(1, state="MERGED", base="agent/m-295-fixes")])

    actor.pulls_changed()
    actor.pulls_changed()

    assert until(lambda: len(board.comments()) == 1)
    assert board.moved() == []
    [(name, comment)] = board.comments()
    assert name == "TASK-1"
    assert "Held from Done:" in comment
    assert PR_ONE in comment
    assert "agent/m-295-fixes" in comment


def test_a_pr_merged_during_the_start_derivation_moves_its_task_to_done_before_that_derivation_ends(
    store: PullStore, stop: threading.Event
) -> None:
    """A restart derives every open task serially; a merge landing in that pass waits one task, not the pass."""
    started = threading.Event()

    class SlowBoard(Board):
        def edit(self, name, changes, comment, /, actor=""):  # type: ignore[no-untyped-def]
            started.set()
            if name != "TASK-999":
                time.sleep(0.1)
            return super().edit(name, changes, comment, actor=actor)

    backlog = [
        task(f"TASK-{100 + n}", "Review", references=(f"https://github.com/acme/trantor/pull/{100 + n}",))
        for n in range(30)
    ]
    late = "https://github.com/acme/trantor/pull/999"
    board = SlowBoard(BoardFeed(), *backlog, task("TASK-999", "Review", references=(late,)))
    store.save([pull(100 + n, state="MERGED") for n in range(30)] + [pull(999, state="OPEN")])
    actor = TaskActor(board.feed, store, board.edit, WAITS, MOVES, create=board.create)
    actor.start(stop)
    assert started.wait(WITHIN_S)

    store.save([pull(999, state="MERGED")])
    merged = time.monotonic()
    actor.pulls_changed()

    assert until(lambda: ("TASK-999", "done") in board.moved())
    assert time.monotonic() - merged < WITHIN_S
    assert not actor.ready.is_set()


#: The portable deliver machine, whose run ends on `DELIVER_FINISHED`.
DELIVERING = {
    "deliver": describe(
        load_machine(Path(__file__).parents[3] / "starpulse" / "skills" / "deliver" / "machine.yaml").machine
    )
}


def test_a_finished_delivery_hands_its_task_and_verdict_to_the_delivered_hook_once(
    store: PullStore, stop: threading.Event
) -> None:
    feed = BoardFeed(roles=ROLES, machines={"board": board_machine(STATUSES), **DELIVERING})
    board = Board(feed, task("TASK-1", "In Progress"))
    delivered: list[tuple[str, str]] = []
    running(board, store, stop, delivered=lambda name, verdict: delivered.append((name, verdict)))
    tasks = MachineTasks(feed)

    def post(event: str, data: dict | None = None) -> None:
        tasks.put(MachineEvent(machine="deliver", event=event, task="TASK-1", time=time.time(), data=data))

    post("PR_OPENED")
    post("DELIVER_FINISHED", {"verdict": "red", "step": "test"})
    post("PR_OPENED")

    assert until(lambda: delivered == [("TASK-1", "red test")])
    assert not until(lambda: len(delivered) > 1, within=0.2)


NOW = 1_800_000_000.0
DAY = 86_400.0
OVERDUE_WAITS = {**WAITS, "waiting": {**WAITS["waiting"], "overdue": "OVERDUE"}}
OVERDUE_MOVES = {**MOVES, ("waiting", "OVERDUE"): "needs_attention"}


def dated(when: str) -> str:
    """`GATED`'s Start Criteria declaring `expect_by: when`."""
    return GATED.replace("    at_least: 1\n", f"    at_least: 1\n    expect_by: '{when}'\n")


def overdue(board: Board, stop: threading.Event, store: PullStore, **options: Any) -> TaskActor:
    """An actor on a clock fixed at `NOW` whose Waiting lane also waits on the SLE deadline, over unmet criteria."""
    options = {"evaluate": Criteria("unmet"), "wall": lambda: NOW} | options
    return running(board, store, stop, waits=OVERDUE_WAITS, moves=OVERDUE_MOVES, **options)


def test_a_waiting_task_past_the_default_sle_moves_to_needs_attention_with_its_age_gate_and_a_question(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Waiting", description=GATED, observed_at=NOW - 8 * DAY))

    overdue(board, stop, store)

    assert until(lambda: board.moved() == [("TASK-1", "needs_attention")])
    (_, changes, _, actor) = board.writes[-1]
    assert actor == ACTOR
    reason = changes["description"]
    assert "## Needs attention" in reason
    assert "8 days" in reason
    assert "7 days from entering Waiting" in reason
    assert "soak" in reason  # the gate still unmet
    assert reason.rstrip().endswith("?")


def test_a_waiting_task_inside_its_sle_stays_and_moves_at_its_own_deadline_with_no_other_event(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(), task("TASK-1", "Waiting", description=GATED, observed_at=time.time() - 7 * DAY + 1.5)
    )

    overdue(board, stop, store, wall=time.time)

    assert board.moved() == []
    assert until(lambda: board.moved() == [("TASK-1", "needs_attention")], within=4.0)  # nothing else touched the task


def test_a_gate_that_holds_beats_a_deadline_that_has_passed(store: PullStore, stop: threading.Event) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Waiting", description=GATED, observed_at=NOW - 30 * DAY))

    overdue(board, stop, store, evaluate=Criteria("met"))

    assert until(lambda: board.moved() == [("TASK-1", "ready")])
    assert not until(lambda: len(board.moved()) > 1, within=0.2)


@pytest.mark.parametrize(
    ("expect_by", "moves"),
    [("2099-01-01T00:00:00+00:00", False), ("2026-01-01T00:00:00+00:00", True)],
)
def test_a_declared_expect_by_replaces_the_default_sle_with_its_date_plus_two_days(
    store: PullStore, stop: threading.Event, expect_by: str, moves: bool
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Waiting", description=dated(expect_by), observed_at=NOW - 60 * DAY))

    overdue(board, stop, store)

    if moves:
        assert until(lambda: board.moved() == [("TASK-1", "needs_attention")])
        assert "expect_by" in board.writes[-1][1]["description"]
    else:
        assert not until(lambda: board.moved(), within=0.3)


def test_a_task_gated_only_on_dependencies_is_not_overdue_while_each_open_one_is_in_progress_or_review(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "In Progress"),
        task("TASK-2", "Waiting", dependencies=("TASK-1",), observed_at=NOW - 30 * DAY),
    )

    overdue(board, stop, store)

    assert board.moved() == []
    board.put(task("TASK-1", "Ready"))  # the blocker's age now counts: the dependency left In Progress
    assert until(lambda: board.moved() == [("TASK-2", "needs_attention")])
    assert "TASK-1" in board.writes[-1][1]["description"]


def test_a_new_expect_by_re_arms_the_deadline(store: PullStore, stop: threading.Event) -> None:
    entered = time.time() - 7 * DAY + 1.5
    board = Board(BoardFeed(), task("TASK-1", "Waiting", description=GATED, observed_at=entered))
    overdue(board, stop, store, wall=time.time)

    board.put(task("TASK-1", "Waiting", description=dated("2099-01-01T00:00:00+00:00"), observed_at=entered))

    time.sleep(2.0)
    assert board.moved() == []


def locked_once(board: Board, locks: int) -> None:
    """Make the board's editor raise SQLite's locked-database error for its first `locks` calls."""
    edit, left = board.edit, [locks]

    def flaky(name: str, changes: Any, comment: Any, /, actor: str = "") -> Written:
        if left[0] > 0:
            left[0] -= 1
            raise sqlite3.OperationalError("database is locked")
        return edit(name, changes, comment, actor=actor)

    board.edit = flaky  # type: ignore[method-assign]


def test_a_move_that_finds_the_board_database_locked_once_retries_and_lands(
    store: PullStore, stop: threading.Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task_actor, "LOCK_BACKOFF_S", (0.0, 0.0))
    board = Board(BoardFeed(), task("TASK-1", "Done"), task("TASK-3", "Waiting", dependencies=("TASK-1",)))
    locked_once(board, 1)

    running(board, store, stop)

    assert until(lambda: board.moved() == [("TASK-3", "ready")])


def test_a_move_that_stays_locked_leaves_the_task_in_its_lane_without_a_needs_attention_reason(
    store: PullStore, stop: threading.Event, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(task_actor, "LOCK_BACKOFF_S", (0.0, 0.0))
    board = Board(BoardFeed(), task("TASK-1", "Done"), task("TASK-3", "Waiting", dependencies=("TASK-1",)))
    locked_once(board, 3)  # the first attempt and both retries

    running(board, store, stop)

    assert until(lambda: "database is locked" in caplog.text)  # logged
    assert board.writes == []  # no Needs attention write
    assert board.tasks["TASK-3"].lane == "waiting"
