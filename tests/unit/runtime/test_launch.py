"""`serve` starts its processes on the interpreter beside the script it was started by, so a symlink moved to a new release
is what the next process runs, and a re-executed `serve` runs from that release's directory."""

from __future__ import annotations

from pathlib import Path

from starpulse.runtime import launch


def _venv(root: Path) -> Path:
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "pyvenv.cfg").write_text("")
    python = root / ".venv" / "bin" / "python"
    python.write_text("")
    (root / ".venv" / "bin" / "starpulse").write_text("")
    return python


def test_the_interpreter_is_the_python_beside_the_script_serve_was_started_by(tmp_path: Path) -> None:
    python = _venv(tmp_path)

    assert launch.interpreter(str(python.parent / "starpulse"), "/usr/bin/python3") == str(python)


def test_a_script_with_no_python_beside_it_falls_back_to_the_running_interpreter(tmp_path: Path) -> None:
    assert launch.interpreter(str(tmp_path / "__main__.py"), "/usr/bin/python3") == "/usr/bin/python3"


def test_the_interpreter_is_not_resolved_through_a_symlink(tmp_path: Path) -> None:
    python = _venv(tmp_path / "release")
    (tmp_path / "current").symlink_to(tmp_path / "release")
    through = tmp_path / "current" / ".venv" / "bin" / "starpulse"

    assert launch.interpreter(str(through), "/usr/bin/python3") == str(
        tmp_path / "current" / ".venv" / "bin" / "python"
    )
    assert python.exists()


def test_the_working_directory_of_a_venv_python_is_the_directory_holding_the_venv(tmp_path: Path) -> None:
    python = _venv(tmp_path)

    assert launch.workdir(str(python)) == tmp_path


def test_a_python_outside_a_venv_has_no_working_directory(tmp_path: Path) -> None:
    assert launch.workdir("/usr/bin/python3") is None
    assert launch.workdir(str(tmp_path / "bin" / "python")) is None
