"""The native board serves one task key, `<task_prefix>-N`, whatever case a task file's `id:` and dependencies spell."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from starpulse.board.adapters.native import board
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog, board_moves, upstream_keys
from starpulse.board.board_feed import BoardFeed
from starpulse.contracts.adapters import BoardTask
from starpulse.runtime.server import history_response

from tests.unit.board.test_native import LANES, native_root, write_task


@pytest.fixture(autouse=True)
def _no_backlog_cli(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path_factory.mktemp("empty-bin")))
    assert shutil.which("backlog") is None


def mixed_board(base: Path, prefix: str = "TASK"):
    """A native board whose prefix is `prefix` and whose files spell the id in both cases."""
    native_root(base).mkdir(parents=True)
    (native_root(base) / "config.yml").write_text(
        yaml.safe_dump({"project_name": "demo", "statuses": LANES, "task_prefix": prefix})
    )
    write_task(base, "task-1", "To Do", dependencies="[TASK-2]")
    write_task(base, "TASK-2", "To Do", dependencies="[task-1]")
    return board({}, base)


def scanned(base: Path) -> dict[str, BoardTask]:
    tasks: list[BoardTask] = []
    UpstreamBacklog(native_root(base), tasks.append).scan()
    return {task.id: task for task in tasks}


def test_canonical_task_key_is_served_for_every_id_and_dependency_the_files_spell(tmp_path: Path) -> None:
    mixed_board(tmp_path)

    served = scanned(tmp_path)

    assert sorted(served) == ["TASK-1", "TASK-2"]
    assert {key: task.dependencies for key, task in served.items()} == {
        "TASK-1": ("TASK-2",),
        "TASK-2": ("TASK-1",),
    }


def test_canonical_task_key_takes_the_case_of_the_configured_prefix(tmp_path: Path) -> None:
    mixed_board(tmp_path, prefix="task")

    assert sorted(scanned(tmp_path)) == ["task-1", "task-2"]


def test_canonical_task_key_leaves_a_dependency_of_another_prefix_as_written(tmp_path: Path) -> None:
    native_root(tmp_path).mkdir(parents=True)
    (native_root(tmp_path) / "config.yml").write_text(
        yaml.safe_dump({"project_name": "demo", "statuses": LANES, "task_prefix": "TASK"})
    )
    write_task(tmp_path, "task-1", "To Do", dependencies="[doc-3, task-1.2]")

    assert scanned(tmp_path)["TASK-1"].dependencies == ("doc-3", "TASK-1.2")


@pytest.mark.parametrize("spelling", ["task-1", "TASK-1", "Task-1"])
def test_canonical_task_key_finds_a_task_whichever_case_the_caller_spells(tmp_path: Path, spelling: str) -> None:
    built = mixed_board(tmp_path)

    assert built.read(spelling)["title"] == "Title"
    assert built.edit(spelling, {"priority": "high"}, "")[0]
    assert built.writer(spelling, "Done", "operator")[0]
    assert built.read("TASK-1")["priority"] == "high"
    assert built.read("TASK-1")["status"] == "Done"
    assert built.archive(spelling, "gone")[0]
    assert built.read(spelling) is None


def test_canonical_task_key_finds_a_file_that_spells_the_id_in_the_other_case(tmp_path: Path) -> None:
    built = mixed_board(tmp_path)

    assert built.read("task-2")["status"] == "To Do"
    assert built.read("Task-2")["status"] == "To Do"


def test_canonical_task_key_is_held_by_the_feed_under_either_spelling(tmp_path: Path) -> None:
    mixed_board(tmp_path)
    machine = {
        "name": "board",
        "states": [
            {"id": "to_do", "name": "To Do", "initial": True, "final": False},
            {"id": "in_progress", "name": "In Progress", "initial": False, "final": False},
            {"id": "done", "name": "Done", "initial": False, "final": True},
        ],
        "transitions": [],
    }
    feed = BoardFeed(keys=upstream_keys("TASK"), machines={"board": machine})
    UpstreamBacklog(native_root(tmp_path), feed.put, board_moves(machine)).scan()

    assert feed.task("task-1")["id"] == "TASK-1"
    assert feed.task("TASK-1")["id"] == "TASK-1"
    assert feed.task("task-9") is None


def test_task_keys_name_the_canonical_key_for_a_branch() -> None:
    keys = upstream_keys("TASK")

    assert keys.for_branch("claude/task-4648-x") == "TASK-4648"
    assert keys.for_branch("refs/heads/claude/TASK-4648") == "TASK-4648"
    assert keys.for_branch("claude/task-4648.2-x") == "TASK-4648.2"
    assert keys.for_branch("main") is None


def test_task_keys_still_match_a_key_in_any_case_and_canonicalise_it() -> None:
    keys = upstream_keys("TASK")

    assert [keys.matches(key) for key in ("task-1", "TASK-1", "Task-1.2", "OPS-1", "TASK-x")] == [
        True,
        True,
        True,
        False,
        False,
    ]
    assert [keys.canonical(key) for key in ("task-1", "TASK-1", "OPS-1", "free text")] == [
        "TASK-1",
        "TASK-1",
        "OPS-1",
        "free text",
    ]


def test_canonical_task_key_is_created_with_the_prefix_case_and_a_lowercase_slug_file(tmp_path: Path) -> None:
    mixed_board(tmp_path)
    built = board({"task_file_name": "slug"}, tmp_path)

    created = built.create("Draw the board", {})

    assert created.output == "TASK-3"
    assert (native_root(tmp_path) / "tasks" / "task-3-draw-the-board.md").exists()
    assert scanned(tmp_path)["TASK-3"].title == "Draw the board"


def test_canonical_task_key_is_the_spelling_the_history_is_asked_under() -> None:
    class Paths:
        def lane_path(self, task: str) -> list[dict]:
            return [{"at": 1.0, "from": None, "to": task}]

    body, status = history_response(Paths(), {"task": ["task-7"]}, (), upstream_keys("TASK"))  # type: ignore[arg-type]

    assert status == 200
    assert json.loads(body)["path"] == [{"at": 1.0, "from": None, "to": "TASK-7"}]
