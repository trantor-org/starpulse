"""The native board's `[board] parked` command: it runs for a task the task actor moved from the working lane to Waiting."""

import shlex
import sys
from pathlib import Path

import pytest
from starpulse.board.adapters import native


def _parked(tmp_path: Path, body: str):
    """The native board's parked over a command that runs `body` (Python) with the task id as `sys.argv[1]`."""
    script = tmp_path / "parked.py"
    script.write_text(body)
    built = native.board({"parked": f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{id}}"}, tmp_path)
    assert built.parked is not None
    return built.parked


def test_the_command_runs_for_the_task_it_is_given(tmp_path: Path) -> None:
    parked = _parked(tmp_path, "import sys, pathlib\npathlib.Path('told').write_text(sys.argv[1])\n")

    parked("TASK-2")

    assert (tmp_path / "told").read_text() == "TASK-2"


def test_a_command_that_exits_nonzero_raises_with_what_it_said(tmp_path: Path) -> None:
    parked = _parked(tmp_path, "import sys\nsys.exit('no holder')\n")

    with pytest.raises(ValueError, match="no holder"):
        parked("TASK-2")


def test_a_board_with_no_parked_command_tells_no_one(tmp_path: Path) -> None:
    assert native.board({}, tmp_path).parked is None


@pytest.mark.parametrize("hook", ["parked", "sent_back", "closed", "released"])
def test_each_notice_command_runs_for_the_task_it_is_given(tmp_path: Path, hook: str) -> None:
    script = tmp_path / "notice.py"
    script.write_text("import sys, pathlib\npathlib.Path('told').write_text(sys.argv[1])\n")
    built = native.board({hook: f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{id}}"}, tmp_path)

    getattr(built, hook)("TASK-3")

    assert (tmp_path / "told").read_text() == "TASK-3"


def test_the_delivered_command_runs_for_the_task_and_the_verdict_it_is_given(tmp_path: Path) -> None:
    script = tmp_path / "notice.py"
    script.write_text("import sys, pathlib\npathlib.Path('told').write_text(' '.join(sys.argv[1:]))\n")
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{id}} {{verdict}}"
    built = native.board({"delivered": command}, tmp_path)

    built.delivered("TASK-3", "red test")

    assert (tmp_path / "told").read_text() == "TASK-3 red test"
