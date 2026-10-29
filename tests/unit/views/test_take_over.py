"""The take-over command hook runs the configured argv with the task id appended and reads its exit status."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starpulse.views.adapters.outbound.take_over import command_take_over


def _script(tmp_path: Path, body: str) -> list[str]:
    path = tmp_path / "take_over.py"
    path.write_text(f"import sys\n{body}\n")
    return [sys.executable, str(path)]


def test_exit_zero_means_the_take_over_was_sent_and_the_task_is_the_last_argument(tmp_path: Path) -> None:
    seen = tmp_path / "seen"
    argv = _script(tmp_path, f"open({str(seen)!r}, 'w').write(sys.argv[-1])")

    assert command_take_over(argv)("TASK-7") is True
    assert seen.read_text() == "TASK-7"


def test_exit_one_means_the_task_has_no_workflow(tmp_path: Path) -> None:
    assert command_take_over(_script(tmp_path, "sys.exit(1)"))("TASK-7") is False


def test_any_other_exit_is_an_error_carrying_the_commands_stderr(tmp_path: Path) -> None:
    argv = _script(tmp_path, "sys.stderr.write('engine unreachable'); sys.exit(2)")

    with pytest.raises(RuntimeError, match="exited 2: engine unreachable"):
        command_take_over(argv)("TASK-7")
