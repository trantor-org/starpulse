"""The server draws the Board its config's `[board]` adapter builds, and keeps history where `database_url` says."""

import time
from pathlib import Path

import pytest

from starpulse.board import Board
from starpulse.config import ConfigError, load
from starpulse.history import DEFAULT_FILE, HistoryStore
from starpulse.server import assemble, history_store
from starpulse.tests import fake_board

TASK = """---
id: task-1
title: Draw the board
status: Doing
---
"""


def _config(tmp_path: Path, text: str = "") -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


def _wait_until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not met within the timeout"
        time.sleep(0.01)


def test_with_no_board_table_the_view_draws_the_backlog_md_project_beside_its_config(tmp_path: Path) -> None:
    (tmp_path / "backlog" / "tasks").mkdir(parents=True)
    (tmp_path / "backlog" / "config.yml").write_text("statuses: [To Do, Doing, Done]\n")
    (tmp_path / "backlog" / "tasks" / "task-1 - Draw-the-board.md").write_text(TASK)

    board, feed = assemble(load(_config(tmp_path)), tmp_path, None, ())
    board.start(feed, "test")

    assert [s["id"] for s in feed.snapshot()["flows"][0]["machine"]["states"]] == ["to_do", "doing", "done"]
    _wait_until(lambda: feed.task("task-1") is not None)
    assert feed.task("task-1")["state"] == "doing"


def test_a_board_type_names_the_module_whose_board_the_view_draws(tmp_path: Path) -> None:
    config = load(_config(tmp_path, '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["open", "shut"]\n'))

    board, feed = assemble(config, tmp_path, None, ())
    board.start(feed, "test")

    snapshot = feed.snapshot()
    assert [s["id"] for s in snapshot["flows"][0]["machine"]["states"]] == ["open", "shut"]
    assert snapshot["cues"] == [{"dag": "q/nightly"}]
    assert feed.task("FAKE-1")["state"] == "open"
    assert feed.task("other-1") is None, "a task outside the adapter's keys is not placed"
    assert fake_board.BUILT == [({"type": "starpulse.tests.fake_board", "lanes": ["open", "shut"]}, tmp_path)]


def test_a_board_type_no_module_provides_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no board adapter of type nowhere.board"):
        load(_config(tmp_path, '[board]\ntype = "nowhere.board"\n'))


def test_without_database_url_history_is_a_sqlite_file_beside_the_config(tmp_path: Path) -> None:
    board, feed = assemble(load(_config(tmp_path)), tmp_path, None, ())

    store = history_store(load(_config(tmp_path)), tmp_path, board, feed.machines)

    assert isinstance(store, HistoryStore)
    assert store.engine.url.database == str(tmp_path / DEFAULT_FILE)


def test_database_url_names_the_database_history_is_kept_in(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'elsewhere.db'}"
    config = load(_config(tmp_path, f'database_url = "{url}"\n'))
    board, feed = assemble(config, tmp_path, None, ())

    store = history_store(config, tmp_path, board, feed.machines)

    assert str(store.engine.url) == url
    assert (tmp_path / "elsewhere.db").is_file()


def test_a_board_that_keeps_its_own_history_is_read_instead(tmp_path: Path) -> None:
    kept = object()
    board = Board(machines=lambda q, w: {}, start=lambda feed, group: None, history=lambda machines: kept)

    assert history_store(load(None), tmp_path, board, {}) is kept
