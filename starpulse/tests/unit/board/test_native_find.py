"""Finding one task's file on the native board matches its id in the raw text, so a read parses the file it returns."""

from pathlib import Path

import pytest

from starpulse._internal.board import native
from starpulse._internal.board.seam import Board

TASKS = 60


def _write(root: Path, name: str, task_id: str, body: str = "") -> None:
    path = root / ".starpulse" / "board" / "tasks" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {task_id}\ntitle: Title of {task_id}\nstatus: To Do\n---\n\n## Description\n{body}\n")


@pytest.fixture
def parses(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The text of every file the native board parses the frontmatter of."""
    seen: list[str] = []
    split = native._split

    def counting(text: str):
        seen.append(text)
        return split(text)

    monkeypatch.setattr(native, "_split", counting)
    return seen


def _board(base: Path) -> Board:
    """The default native board of `base`, created empty before any task file is written."""
    return native.board({"path": ".starpulse/board"}, base)


def _read(built: Board, task: str) -> dict | None:
    assert built.read is not None
    return built.read(task)


def test_reading_one_task_of_a_large_board_parses_only_its_own_file(tmp_path: Path, parses: list[str]) -> None:
    built = _board(tmp_path)
    for number in range(TASKS):
        _write(tmp_path, f"task-{number} - Title", f"task-{number}")

    record = _read(built, "task-42")

    assert record is not None and record["title"] == "Title of task-42"
    assert len(parses) <= 2


def test_a_task_named_only_in_another_tasks_body_is_not_found(tmp_path: Path) -> None:
    built = _board(tmp_path)
    for number in range(TASKS):
        _write(tmp_path, f"task-{number} - Title", f"task-{number}", body="id: task-900\n" if number == 1 else "")

    assert _read(built, "task-900") is None


def test_a_task_whose_file_name_does_not_carry_its_id_is_still_found(tmp_path: Path) -> None:
    built = _board(tmp_path)
    for number in range(TASKS):
        _write(tmp_path, f"task-{number} - Title", f"task-{number}")
    _write(tmp_path, "renamed by hand", "task-500")

    record = _read(built, "task-500")

    assert record is not None and record["title"] == "Title of task-500"
