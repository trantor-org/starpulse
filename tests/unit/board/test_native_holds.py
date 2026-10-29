"""The native board's `[board] holds` command: the reasons it prints withhold a task's `deps_done` from the task actor."""

import shlex
import sys
from pathlib import Path

import pytest
from starpulse.board.adapters import native


def _holds(tmp_path: Path, body: str):
    """The native board's holds over a command that runs `body` (Python) with the task id as `sys.argv[1]`."""
    script = tmp_path / "holds.py"
    script.write_text(body)
    built = native.board({"holds": f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{id}}"}, tmp_path)
    assert built.holds is not None
    return built.holds


def test_the_command_prints_the_reasons_for_the_task_it_is_given(tmp_path: Path) -> None:
    holds = _holds(
        tmp_path,
        "import json, sys\nprint(json.dumps([f'{sys.argv[1]} has an uncut slice'] if sys.argv[1] == 'TASK-2' else []))\n",
    )

    assert holds("TASK-2") == ["TASK-2 has an uncut slice"]
    assert holds("TASK-3") == []


def test_a_command_that_prints_no_reason_list_raises_so_the_actor_holds_the_task(tmp_path: Path) -> None:
    holds = _holds(tmp_path, "print('not json')\n")

    with pytest.raises(ValueError, match="not json"):
        holds("TASK-2")


def test_a_board_without_the_setting_holds_nothing(tmp_path: Path) -> None:
    assert native.board({}, tmp_path).holds is None


def test_the_unfinished_command_prints_the_work_a_merged_task_still_has(tmp_path: Path) -> None:
    script = tmp_path / "unfinished.py"
    script.write_text("import json, sys\nprint(json.dumps([f'{sys.argv[1]} lacks a PR'] if sys.argv[1] == 'TASK-2' else []))\n")
    built = native.board({"unfinished": f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{id}}"}, tmp_path)

    assert built.unfinished is not None
    assert built.unfinished("TASK-2") == ["TASK-2 lacks a PR"]
    assert built.unfinished("TASK-3") == []
    assert native.board({}, tmp_path).unfinished is None
