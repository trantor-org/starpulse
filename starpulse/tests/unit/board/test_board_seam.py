"""The server draws the Board its config's `[board]` adapter builds, and keeps history where `database_url` says."""

import ast
import time
from dataclasses import fields
from pathlib import Path

import pytest

from starpulse.board.model.seam import Board
from starpulse.board.model.seam import load as load_board
from starpulse._internal.config.config import ConfigError, load
from starpulse._internal.server.assembly import assemble, history_store
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import DEFAULT_FILE
from starpulse.flow_metrics.history import HistoryStore
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


def test_a_board_type_upstream_backlog_draws_the_backlog_md_project_beside_its_config(tmp_path: Path) -> None:
    (tmp_path / "backlog" / "tasks").mkdir(parents=True)
    (tmp_path / "backlog" / "config.yml").write_text("project_name: demo\nstatuses: [To Do, Doing, Done]\n")
    (tmp_path / "backlog" / "tasks" / "task-1 - Draw-the-board.md").write_text(TASK)

    config = load(_config(tmp_path, '[board]\ntype = "upstream_backlog"\n'))
    board, feed = assemble(config, tmp_path, None, ())
    board.start(feed, "test", EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))

    assert [s["id"] for s in feed.snapshot()["flows"][0]["machine"]["states"]] == ["to_do", "doing", "done"]
    _wait_until(lambda: feed.task("task-1") is not None)
    task = feed.task("task-1")
    assert task is not None and task["state"] == "doing"


def test_a_board_type_names_the_module_whose_board_the_view_draws(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fake_board, "BUILT", [])  # mutmut reruns the suite in one process
    config = load(_config(tmp_path, '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["open", "shut"]\n'))

    board, feed = assemble(config, tmp_path, None, ())
    board.start(feed, "test", EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))

    snapshot = feed.snapshot()
    assert [s["id"] for s in snapshot["flows"][0]["machine"]["states"]] == ["open", "shut"]
    assert snapshot["cues"] == [{"event": "SHUT", "dag": "q/nightly", "state": "shut"}]
    task = feed.task("FAKE-1")
    assert task is not None and task["state"] == "open"
    assert feed.task("other-1") is None, "a task outside the adapter's keys is not placed"
    assert fake_board.BUILT == [({"type": "starpulse.tests.fake_board", "lanes": ["open", "shut"]}, tmp_path)]


def test_the_board_draws_its_machines_knowing_every_configured_workflow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fake_board, "BUILT", [])
    monkeypatch.setattr(fake_board, "DRAWN", [])
    config = load(
        _config(
            tmp_path,
            '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["open", "shut"]\n\n'
            '[[runs]]\nname = "prod"\ntype = "dagu"\nurl = "http://prod.example.test:8085"\n'
            '[runs.domains]\nOps = ["nightly", "backup"]\nData = ["etl"]\n',
        )
    )

    assemble(config, tmp_path, None, ())

    assert fake_board.DRAWN == [["prod/nightly", "prod/backup", "prod/etl"]]


def test_a_board_type_no_module_provides_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no board adapter of type nowhere.board"):
        load(_config(tmp_path, '[board]\ntype = "nowhere.board"\n'))


def test_without_database_url_history_is_a_sqlite_file_beside_the_config(tmp_path: Path) -> None:
    _, feed = assemble(load(_config(tmp_path)), tmp_path, None, ())

    store = history_store(load(_config(tmp_path)), tmp_path, feed.machines)

    assert isinstance(store, HistoryStore)
    assert store.engine.url.database == str(tmp_path / DEFAULT_FILE)
    assert store.machine_path("task-1", "board") == ([], 0), "the store places steps on the drawn machines"


def test_database_url_names_the_database_history_is_kept_in(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'elsewhere.db'}"
    config = load(_config(tmp_path, f'database_url = "{url}"\n'))
    _, feed = assemble(config, tmp_path, None, ())

    store = history_store(config, tmp_path, feed.machines)

    assert isinstance(store, HistoryStore)
    assert str(store.engine.url) == url
    assert (tmp_path / "elsewhere.db").is_file()


def test_no_board_keeps_a_history_of_its_own() -> None:
    assert "history" not in {field.name for field in fields(Board)}, "StarPulse's store is the only history"


def test_a_feed_draws_the_tracker_and_the_window_its_config_and_caller_give(tmp_path: Path) -> None:
    config = load(_config(tmp_path, 'tracker_url = "http://tracker.test"\n'))

    _, feed = assemble(config, tmp_path, 3600.0, ())

    assert (feed.snapshot()["boardUrl"], feed._window_s) == ("http://tracker.test", 3600.0)


def test_a_board_type_whose_module_builds_no_board_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as refused:
        load_board("starpulse.contracts", {}, tmp_path)

    assert str(refused.value) == "board type starpulse.contracts: starpulse.contracts has no board(settings, base)"


SEAM_FILES = (
    "board/model/seam.py",
    "_internal/kit/adapter_kit.py",
    "_internal/server/asgi_app.py",
    "_internal/server/reads.py",
    "_internal/server/write_routes.py",
    "_internal/server/services.py",
)
MOST_PARAMETERS = 12


def _seam_functions() -> list[tuple[str, int]]:
    """Every function the Board seam and its server side define, with the number of parameters it takes."""
    root = Path(__file__).parents[3]
    rows = []
    for name in SEAM_FILES:
        for node in ast.walk(ast.parse((root / name).read_text())):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                args = node.args
                count = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
                rows.append((f"{name}:{node.name}", count + bool(args.vararg) + bool(args.kwarg)))
    return rows


def test_no_seam_function_takes_more_than_a_dozen_parameters() -> None:
    wide = [row for row in _seam_functions() if row[1] > MOST_PARAMETERS]

    assert wide == []


def test_the_seam_declares_no_one_method_protocols() -> None:
    source = (Path(__file__).parents[3] / "board" / "model" / "seam.py").read_text()
    protocols = [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef) and any(ast.unparse(base).endswith("Protocol") for base in node.bases)
    ]

    assert protocols == []


def test_written_carries_the_lane_and_the_moment_it_was_written() -> None:
    """A write that moves a task records the lane it moved to and the moment it was written, so the server can
    record the change with the request's actor at write time."""
    from starpulse.board.model.seam import Written

    written = Written(ok=True, lane="in_progress", at=100.0)

    assert (written.lane, written.at) == ("in_progress", 100.0)


def test_a_write_that_moves_no_lane_leaves_the_lane_unset() -> None:
    """A write that changes no lane (a note, a refusal) records no lane, so the server records nothing for it."""
    from starpulse.board.model.seam import Written

    written = Written(ok=True)

    assert written.lane is None
