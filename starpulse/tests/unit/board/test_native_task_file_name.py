"""`[board] task_file_name`: the form of the file name a created task is written under."""

from pathlib import Path

import pytest

from starpulse._internal.board.native import board
from starpulse._internal.board.seam import Board


def _created(tmp_path: Path, title: str, **settings: str) -> str:
    """The name of the one file creating a task titled `title` on a native board with `settings` wrote."""
    built: Board = board(settings, tmp_path)
    assert built.create is not None
    assert built.create(title, {}).ok
    (path,) = (tmp_path / ".starpulse" / "board" / "tasks").glob("*.md")
    return path.name


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("Draw the board", "task-1-draw-the-board.md"),
        ("Let a native StarPulse board name task files", "task-1-let-a-native.md"),
        ("Fix the parser and the lexer", "task-1-fix-the-parser.md"),
        ("Check the nightly sweep 2026-10-09", "task-1-check-the-nightly-2026-10-09.md"),
        ("Supercalifragilisticexpialidocious", "task-1-supercalifragilisti.md"),
        ("What's new: Ünïcode & symbols", "task-1-what-s-new-n-code.md"),
        ("!!!", "task-1-untitled.md"),
    ],
)
def test_the_slug_form_names_a_task_task_n_slug_with_the_slug_capped_at_a_word(
    tmp_path: Path, title: str, name: str
) -> None:
    assert _created(tmp_path, title, task_file_name="slug") == name


@pytest.mark.parametrize("settings", [{}, {"task_file_name": "title"}])
def test_a_board_without_the_slug_form_keeps_the_task_id_space_dash_title_name(
    tmp_path: Path, settings: dict[str, str]
) -> None:
    name = _created(tmp_path, "Let a native StarPulse board name task files", **settings)

    assert name == "task-1 - Let-a-native-StarPulse-board-name-task-files.md"


def test_a_task_in_a_slug_named_file_is_read_by_its_id(tmp_path: Path) -> None:
    built = board({"task_file_name": "slug"}, tmp_path)
    assert built.create is not None and built.read is not None
    task = built.create("Draw the board", {}).output

    record = built.read(task)
    assert record is not None and record["title"] == "Draw the board"


def test_a_file_name_form_the_board_does_not_know_is_refused_when_it_loads(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"task_file_name.*slug.*title"):
        board({"task_file_name": "stem"}, tmp_path)
