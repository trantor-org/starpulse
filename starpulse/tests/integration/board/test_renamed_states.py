"""A board whose States are renamed (`todo`, `doing`, `on_me`, `shipped`) runs through the native writer, the lifecycle
verbs, the feed, the Scheduler and Flow Metrics: each reads the roles the machine declares and none a State's name."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from starpulse.flow_metrics.level import Level, Terminal
from starpulse.scheduler.model.config import Scheduler
from starpulse.board.adapters.native import board
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.level_metrics import Run, level_metrics
from starpulse.scheduler.model.inputs import review_points
from starpulse.tests.unit.board.test_native import native_root, write_task
from starpulse.views.writes import claim_task, park_task, review_task

LAN = "127.0.0.1"
PULL = "https://github.com/acme/app/pull/5"
FIXTURE = Path(__file__).parents[2] / "fixtures" / "machines" / "renamed-board.yaml"
STATUSES = ["Inbox", "Todo", "Parked", "Doing", "Checking", "On me", "Shipped", "Gone"]
LEGACY = {"new", "ready", "waiting", "in_progress", "needs_attention", "review", "done", "archived"}


def _renamed(
    base: Path, monkeypatch: pytest.MonkeyPatch, tasks: dict[str, tuple[str, dict[str, object]]]
) -> tuple[BoardFeed, Board]:
    """A native board over `renamed-board.yaml`, holding `tasks` as (status, fields) by id."""
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, scanned: (self.scan(), scanned()))
    (base / "board.yaml").write_text(FIXTURE.read_text())
    native_root(base).mkdir(parents=True)
    (native_root(base) / "config.yml").write_text(
        yaml.safe_dump({"project_name": "demo", "statuses": STATUSES, "task_prefix": "task"})
    )
    for task, (status, fields) in tasks.items():
        write_task(base, task, status, **fields)
    built = board({"machine": "board.yaml"}, base)
    feed = BoardFeed(machines=built.machines(lambda name: name, ()), keys=built.keys, roles=built.roles)
    built.start(feed, "test", EventLog(f"sqlite:///{base / 'events.sqlite'}"))
    return feed, built


def _scan(base: Path, feed: BoardFeed) -> None:
    """Place what the last write changed: the board's poll does it in a running server."""
    UpstreamBacklog(native_root(base), feed.put).scan()


def _text(base: Path, task: str) -> str:
    return next((native_root(base) / "tasks").glob(f"{task} - *.md")).read_text()


def _states(feed: BoardFeed) -> dict[str, str]:
    return {agent["id"]: agent["state"] for agent in feed.open_tasks()}


def _claim(feed: BoardFeed, built: Board, **body: object) -> tuple[int, dict[str, Any]]:
    assert built.writer is not None
    return claim_task(LAN, json.dumps(body).encode(), feed, built.writer)


def _park(feed: BoardFeed, built: Board, **body: object) -> tuple[int, dict[str, Any]]:
    return park_task(LAN, json.dumps(body).encode(), feed, built.read, built.edit)


def _review(feed: BoardFeed, built: Board, **body: object) -> tuple[int, dict[str, Any]]:
    return review_task(LAN, json.dumps(body).encode(), feed, built.read, built.edit)


def test_the_board_reads_its_roles_from_the_machine_it_was_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feed, built = _renamed(tmp_path, monkeypatch, {})

    assert built.roles.wire() == {
        "initial": "inbox",
        "final": "gone",
        "done": "shipped",
        "working": "doing",
        "ready": "todo",
        "waiting": "parked",
        "review": "checking",
        "attention": "on_me",
        "startable": ["on_me", "parked", "todo"],
    }
    assert feed.snapshot()["roles"] == built.roles.wire()


def test_a_claim_moves_a_task_into_the_working_state_and_records_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _renamed(tmp_path, monkeypatch, {"task-1": ("Todo", {})})

    assert _claim(feed, built, task="task-1", session="s-1") == (
        200,
        {"task": "task-1", "to": "doing", "assignee": "s-1"},
    )

    _scan(tmp_path, feed)
    assert "status: Doing\n" in _text(tmp_path, "task-1")
    assert _states(feed) == {"task-1": "doing"}


def test_a_claim_of_a_task_still_being_worked_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    feed, built = _renamed(tmp_path, monkeypatch, {"task-1": ("Doing", {})})

    status, _ = _claim(feed, built, task="task-1", session="s-1")

    assert status == 409


def test_parking_names_the_waiting_state_for_a_dependency_and_the_attention_state_for_the_operator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _renamed(
        tmp_path, monkeypatch, {"task-1": ("Doing", {}), "task-2": ("Todo", {}), "task-3": ("Doing", {})}
    )

    assert _park(feed, built, task="task-1", untilTask=["task-2"])[1]["to"] == "parked"
    assert _park(feed, built, task="task-3", operator="which one?")[1]["to"] == "on_me"


def test_a_review_moves_the_task_into_the_state_that_waits_on_its_pull_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, built = _renamed(tmp_path, monkeypatch, {"task-1": ("Doing", {})})

    assert _review(feed, built, task="task-1", references=[PULL])[1]["to"] == "checking"


def test_a_task_in_the_done_state_completes_and_one_still_being_worked_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, built = _renamed(tmp_path, monkeypatch, {"task-1": ("Shipped", {}), "task-2": ("Doing", {})})
    assert built.complete is not None

    assert built.complete("task-1").ok
    assert not built.complete("task-2").ok


def test_a_created_task_starts_in_the_initial_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, built = _renamed(tmp_path, monkeypatch, {})
    (native_root(tmp_path) / "tasks").mkdir()
    assert built.create is not None

    written = built.create("Made", {})

    assert written.ok, written.output
    assert "status: Inbox\n" in next((native_root(tmp_path) / "tasks").glob("*Made*.md")).read_text()


def test_archiving_a_task_releases_a_waiting_dependent_into_the_state_that_waits_to_be_picked_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, built = _renamed(
        tmp_path, monkeypatch, {"task-1": ("Todo", {}), "task-2": ("Parked", {"dependencies": "[task-1]"})}
    )
    assert built.archive is not None

    assert built.archive("task-1", "dropped").ok

    assert "status: Todo\n" in _text(tmp_path, "task-2")


def test_a_task_in_the_waiting_state_is_listed_with_that_state_in_the_feed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, _ = _renamed(
        tmp_path, monkeypatch, {"task-1": ("Shipped", {}), "task-2": ("Parked", {"dependencies": "[task-1]"})}
    )

    assert _states(feed)["task-2"] == "parked"


def test_the_scheduler_counts_the_review_load_in_the_state_that_waits_on_a_pull_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed, _ = _renamed(tmp_path, monkeypatch, {"task-1": ("Checking", {}), "task-2": ("Doing", {})})
    policy = Scheduler()

    lane = policy.reviewed_lane(feed.roles.review)

    assert lane == "checking"
    assert review_points(feed.open_tasks(), lane, policy.unsized_points) == policy.unsized_points


def test_flow_metrics_tell_the_working_and_the_goal_states_apart_without_their_names() -> None:
    hour = 3600.0
    machine = {
        "states": [
            {"id": "inbox", "initial": True, "final": False},
            {"id": "doing", "initial": False, "final": False},
            {"id": "shipped", "initial": False, "final": False},
            {"id": "gone", "initial": False, "final": True},
        ]
    }
    level = Level("board", "shipped", (Terminal("shipped", "goal"), Terminal("gone", "abandoned")))
    runs = [
        Run("a", "A1", ((10 * hour, "inbox"), (20 * hour, "doing"), (30 * hour, "shipped"))),
        Run("a", "A2", ((40 * hour, "doing"),)),
    ]

    metrics = level_metrics(level, machine, runs, now=48 * hour, window_s=38 * hour)

    assert metrics["wip"]["states"] == {"doing": 1}
    assert metrics["throughput"]["count"] == 1


def test_a_state_name_built_at_run_time_is_no_claim_on_the_renamed_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scan for literals misses `f"{x}_progress"`; the renamed board catches it, for the writer takes only the
    machine's working State as a claim and records an assignee for no other."""
    _, built = _renamed(tmp_path, monkeypatch, {"task-1": ("Todo", {}), "task-2": ("Todo", {})})
    assert built.writer is not None
    stem = "in"

    assert LEGACY.isdisjoint(built.roles.roles)
    built.writer("task-1", "doing", "agent", "s-1")
    built.writer("task-2", f"{stem}_progress", "agent", "s-2")

    assert "s-1" in _text(tmp_path, "task-1")
    assert "s-2" not in _text(tmp_path, "task-2")
