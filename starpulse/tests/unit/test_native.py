"""The native board: StarPulse's own Markdown tasks under `.starpulse/board/`, created on first serve and written in Python."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from starpulse.adapter_kit import BoardAdapterKit
from starpulse.board import Board
from starpulse.board_feed import BoardFeed
from starpulse.config import load
from starpulse.contracts import BoardTask
from starpulse.event_log import EventLog
from starpulse.machine_definition import Writer
from starpulse.native import board
from starpulse.server import announce, assemble, move_task
from starpulse.upstream_backlog import UpstreamBacklog, board_moves, upstream_keys

LANES = ["To Do", "In Progress", "Done"]
_OPERATOR_ONLY = """\
name: board
states:
  to_do: {initial: true}
  in_progress: {}
  done: {final: true}
events:
  to_in_progress: [{from: to_do, to: in_progress}]
  RETURN: [{from: in_progress, to: to_do}]
  to_done: [{from: in_progress, to: done}]
writers:
  RETURN: [{actor: operator, trigger: manual}]
"""


def native_root(base: Path) -> Path:
    return base / ".starpulse" / "board"


def write_task(base: Path, task_id: str, status: str, **fields: object) -> Path:
    """One task file as the native board keeps it: YAML frontmatter, then the description section."""
    extra = "".join(f"{key}: {value}\n" for key, value in fields.items())
    path = native_root(base) / "tasks" / f"{task_id} - Title.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {task_id}\ntitle: Title\nstatus: {status}\n{extra}---\n\n"
        "<!-- SECTION:DESCRIPTION:BEGIN -->\nWhy\n<!-- SECTION:DESCRIPTION:END -->\n"
    )
    return path


def project(base: Path, status: str = "In Progress") -> tuple[Path, Board]:
    """A native board holding `task-1` in `status`, whose machine leaves the move back to To Do to the operator."""
    (base / "board.yaml").write_text(_OPERATOR_ONLY)
    native_root(base).mkdir(parents=True)
    (native_root(base) / "config.yml").write_text(
        yaml.safe_dump({"project_name": "demo", "statuses": LANES, "task_prefix": "task"})
    )
    return write_task(base, "task-1", status), board({"machine": "board.yaml"}, base)


def scanned(base: Path) -> list[BoardTask]:
    tasks: list[BoardTask] = []
    UpstreamBacklog(native_root(base), tasks.append).scan()
    return tasks


@pytest.fixture(autouse=True)
def _no_backlog_cli(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """The native board writes with Python alone: nothing named `backlog` is on PATH."""
    monkeypatch.setenv("PATH", str(tmp_path_factory.mktemp("empty-bin")))
    assert shutil.which("backlog") is None


def test_serving_in_an_empty_directory_creates_the_default_lanes_and_an_empty_tasks_directory(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    built, feed = assemble(load(None), tmp_path, None, ())
    built.start(feed, "test", EventLog(f"sqlite:///{tmp_path_factory.mktemp('log') / 'events.sqlite'}"))

    created = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert created == [
        ".starpulse",
        ".starpulse/board",
        ".starpulse/board/config.yml",
        ".starpulse/board/tasks",
    ]
    assert yaml.safe_load((native_root(tmp_path) / "config.yml").read_text()) == {
        "project_name": tmp_path.name,
        "statuses": LANES,
        "task_prefix": "task",
    }
    flow, harness = feed.snapshot()["flows"]
    assert [state["id"] for state in flow["machine"]["states"]] == ["to_do", "in_progress", "done"]
    assert flow["agents"] == []
    assert harness["name"] == "harness"


def test_serving_again_leaves_a_board_the_user_edited_as_it_is(tmp_path: Path) -> None:
    native_root(tmp_path).mkdir(parents=True)
    (native_root(tmp_path) / "config.yml").write_text("project_name: demo\nstatuses: [Open, Shut]\ntask_prefix: bug\n")

    built, feed = assemble(load(None), tmp_path, None, ())

    assert sorted(path.name for path in native_root(tmp_path).iterdir()) == ["config.yml"]
    assert [state["id"] for state in feed.snapshot()["flows"][0]["machine"]["states"]] == ["open", "shut"]
    assert built.keys is not None and built.keys.matches("bug-3")


def test_a_move_the_machine_allows_rewrites_the_status_in_the_task_file(tmp_path: Path) -> None:
    path, built = project(tmp_path)
    before = path.read_text()
    assert built.writer is not None

    written = built.writer("task-1", "Done", "operator")

    assert written.ok
    assert path.read_text() == before.replace("status: In Progress", "status: Done")
    assert [(task.id, task.lane) for task in scanned(tmp_path)] == [("task-1", "done")]


def test_an_agents_claim_records_its_session_as_the_holder_and_an_operators_move_does_not(tmp_path: Path) -> None:
    _, built = project(tmp_path, "To Do")
    assert built.writer is not None

    assert built.writer("task-1", "In Progress", "agent", "0d617371").ok
    assert [(task.lane, task.holder) for task in scanned(tmp_path)] == [("in_progress", "0d617371")]
    assert built.writer("task-1", "Done", "operator").ok
    assert [task.holder for task in scanned(tmp_path)] == ["0d617371"]


def test_a_move_the_machine_leaves_to_the_operator_is_refused_to_an_agent_with_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, built = project(tmp_path)
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval: self.scan())
    feed = BoardFeed(machines=built.machines(lambda name: name, ()), keys=built.keys)
    built.start(feed, "test", EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))

    def move(actor: str) -> tuple[int, dict]:
        raw = json.dumps({"task": "task-1", "to": "to_do", "actor": actor}).encode()
        assert built.writer is not None
        return move_task("127.0.0.1", raw, feed, built.writer)

    refused = move("agent")
    assert refused[0] == 409 and "operator" in refused[1]["error"]
    assert "status: In Progress\n" in path.read_text()
    assert move("operator") == (200, {"task": "task-1", "to": "to_do"})
    assert "status: To Do\n" in path.read_text()


def test_an_assignee_change_is_written_to_the_task_file(tmp_path: Path) -> None:
    path, built = project(tmp_path)
    assert built.assign is not None

    assert built.assign("task-1", "@agent-deep-high").ok

    assert [task.assignee for task in scanned(tmp_path)] == ["@agent-deep-high"]
    assert "status: In Progress\n" in path.read_text()


def test_a_task_the_board_does_not_hold_is_refused_by_both_writers(tmp_path: Path) -> None:
    _, built = project(tmp_path)
    assert built.writer is not None and built.assign is not None

    for written in (built.writer("task-9", "Done", "operator"), built.assign("task-9", "@a")):
        assert not written.ok and "task-9" in written.output


def test_a_setting_the_native_board_does_not_read_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="command"):
        board({"command": "backlog"}, tmp_path)


def test_with_a_backlog_md_project_beside_the_default_config_the_snapshot_and_banner_name_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "backlog").mkdir()
    (tmp_path / "backlog" / "config.yml").write_text("project_name: demo\nstatuses: [To Do, Done]\n")

    _, feed = assemble(load(None), tmp_path, None, ())

    hint = feed.snapshot()["hint"]
    assert str(tmp_path / "backlog" / "config.yml") in hint
    assert hint.endswith("run: starpulse connect backlog --path backlog")
    assert "\n" not in hint
    announce(8766, hint)
    assert capsys.readouterr().out.splitlines() == ["StarPulse on :8766", hint]


@pytest.mark.parametrize("table", ['[board]\ntype = "native"\n', '[board]\ntype = "upstream_backlog"\n'])
def test_a_config_that_names_a_board_gets_no_backlog_md_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], table: str
) -> None:
    (tmp_path / "backlog").mkdir()
    (tmp_path / "backlog" / "config.yml").write_text("project_name: demo\nstatuses: [To Do, Done]\n")
    (tmp_path / "starpulse.toml").write_text(table)

    _, feed = assemble(load(tmp_path / "starpulse.toml"), tmp_path, None, ())

    assert feed.snapshot()["hint"] is None
    announce(8766, feed.snapshot()["hint"])
    assert capsys.readouterr().out == "StarPulse on :8766\n"


def test_with_no_backlog_md_project_the_default_config_has_no_hint(tmp_path: Path) -> None:
    _, feed = assemble(load(None), tmp_path, None, ())

    assert feed.snapshot()["hint"] is None


class TestNativeBoardAdapter(BoardAdapterKit):
    keys = upstream_keys("task")
    teams = {"task-1": "demo", "task-2": "demo"}
    branches = {"feature/task-12-add-x": "task-12", "main": None}

    @pytest.fixture(autouse=True)
    def _project(self, tmp_path: Path) -> None:
        """The fixture project: its In Progress task may go to Done by anyone and back to To Do only by the operator."""
        _, built = project(tmp_path)
        write_task(tmp_path, "task-2", "To Do")
        self.base, self.writer = tmp_path, built.writer
        self.machines = built.machines(lambda name: name, ())
        self.moves = board_moves(self.machines["board"], {"RETURN": (Writer("operator", "manual"),)})

    def produce(self) -> list[dict]:
        tasks: list[BoardTask] = []
        UpstreamBacklog(native_root(self.base), tasks.append, self.moves).scan()
        return [task.model_dump(mode="json") for task in tasks]
