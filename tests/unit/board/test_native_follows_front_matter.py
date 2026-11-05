"""A native create writes `follows` as front matter, the feed and DTO read it back, and an edit sets and clears it."""

from pathlib import Path

from starpulse.board.adapters import native
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog, _split
from starpulse.board.model.feed.shared import task_agent
from starpulse.contracts.api.dto.task import RawTask


def _board_root(base: Path) -> Path:
    return base / ".starpulse" / "board"


def _task_front(base: Path) -> dict:
    (path,) = (_board_root(base) / "tasks").iterdir()
    return _split(path.read_text())[0]


def test_create_writes_follows_to_the_task_file(tmp_path: Path) -> None:
    assert native.board({}, tmp_path).create("Follow up", {"follows": "TASK-12"}, actor="adin").ok

    assert _task_front(tmp_path)["follows"] == "TASK-12"


def test_create_without_follows_leaves_the_key_out(tmp_path: Path) -> None:
    assert native.board({}, tmp_path).create("Follow up", {}, actor="adin").ok

    assert "follows" not in _task_front(tmp_path)


def test_follows_reaches_the_board_feed_and_dto(tmp_path: Path) -> None:
    assert native.board({}, tmp_path).create("Follow up", {"follows": "TASK-12"}, actor="adin").ok
    tasks = []
    UpstreamBacklog(_board_root(tmp_path), tasks.append).scan()

    (task,) = tasks
    agent = task_agent(task)

    assert agent["follows"] == "TASK-12"
    assert RawTask.model_validate(agent).follows == "TASK-12"


def test_follows_reaches_the_task_record(tmp_path: Path) -> None:
    assert native.board({}, tmp_path).create("Follow up", {"follows": "TASK-12"}, actor="adin").ok
    (path,) = (_board_root(tmp_path) / "tasks").iterdir()

    assert native._record_of(path.read_text(), "TASK-1", lambda *_: [])["follows"] == "TASK-12"


def test_an_edit_sets_and_clears_follows(tmp_path: Path) -> None:
    built = native.board({}, tmp_path)
    task = built.create("Follow up", {}, actor="adin").output

    assert built.edit(task, {"follows": "TASK-12"}, "").ok
    assert _task_front(tmp_path)["follows"] == "TASK-12"
    assert built.edit(task, {"follows": ""}, "").ok
    assert "follows" not in _task_front(tmp_path)
