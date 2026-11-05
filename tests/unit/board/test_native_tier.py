"""A native create writes `tier` as front matter (`standard` when none is named), an edit sets it, and every reader sees it."""

from pathlib import Path

from starpulse.board.adapters import native
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog, _split
from starpulse.board.feed.shared import task_agent
from starpulse.contracts.api.dto.task import RawTask


def _board_root(base: Path) -> Path:
    return base / ".starpulse" / "board"


def _task_front(base: Path) -> dict:
    (path,) = (_board_root(base) / "tasks").iterdir()
    return _split(path.read_text())[0]


def test_create_writes_the_tier_it_names(tmp_path: Path) -> None:
    assert native.board({}, tmp_path).create("Fix it", {"tier": "bug"}, actor="adin").ok

    assert _task_front(tmp_path)["tier"] == "bug"


def test_create_without_a_tier_writes_standard(tmp_path: Path) -> None:
    assert native.board({}, tmp_path).create("Add it", {}, actor="adin").ok

    assert _task_front(tmp_path)["tier"] == "standard"


def test_tier_reaches_the_board_feed_and_dto(tmp_path: Path) -> None:
    assert native.board({}, tmp_path).create("Speed it", {"tier": "leverage"}, actor="adin").ok
    tasks = []
    UpstreamBacklog(_board_root(tmp_path), tasks.append).scan()

    (task,) = tasks
    agent = task_agent(task)

    assert agent["tier"] == "leverage"
    assert RawTask.model_validate(agent).tier == "leverage"


def test_tier_reaches_the_task_record(tmp_path: Path) -> None:
    assert native.board({}, tmp_path).create("Fix it", {"tier": "bug"}, actor="adin").ok
    (path,) = (_board_root(tmp_path) / "tasks").iterdir()

    assert native._record_of(path.read_text(), "TASK-1", lambda *_: [])["tier"] == "bug"


def test_an_edit_sets_the_tier_and_clearing_it_leaves_standard(tmp_path: Path) -> None:
    built = native.board({}, tmp_path)
    task = built.create("Fix it", {}, actor="adin").output

    assert built.edit(task, {"tier": "regression"}, "").ok
    assert _task_front(tmp_path)["tier"] == "regression"
    assert built.edit(task, {"tier": ""}, "").ok
    assert "tier" not in _task_front(tmp_path)


def test_a_tier_the_board_does_not_name_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    built = native.board({}, tmp_path)
    task = built.create("Fix it", {}, actor="adin").output

    refused = built.edit(task, {"tier": "urgent"}, "")

    assert not refused.ok
    assert "tier must be one of" in refused.output
    assert _task_front(tmp_path)["tier"] == "standard"
