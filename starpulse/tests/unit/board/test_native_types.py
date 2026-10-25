"""The native board's `[board] types`: the names a task's `type` may take, enforced where every task write lands."""

from pathlib import Path

import pytest

from starpulse.board.adapters.native import board
from starpulse.board.model.seam import Board
from starpulse.tests.unit.board.test_native import native_root, write_task

TYPES = ["spike", "story"]


def typed(base: Path, types: list[str] | None, **fields: object) -> tuple[Path, Board]:
    """A native board declaring `types` (none when None), holding `task-1` in `In Progress`."""
    board({}, base)  # makes the default lanes
    return write_task(base, "task-1", "In Progress", **fields), board({} if types is None else {"types": types}, base)


def test_an_edit_to_a_type_outside_the_declared_list_is_refused_with_the_list_and_writes_nothing(tmp_path: Path) -> None:
    path, built = typed(tmp_path, TYPES)
    assert built.edit is not None
    before = path.read_text()

    written = built.edit("task-1", {"type": "epic"}, "")

    assert not written.ok
    assert "epic" in written.output and "spike, story" in written.output
    assert path.read_text() == before


def test_an_edit_to_a_declared_type_lands(tmp_path: Path) -> None:
    path, built = typed(tmp_path, TYPES)
    assert built.edit is not None

    assert built.edit("task-1", {"type": "spike"}, "").ok
    assert "type: spike\n" in path.read_text()


def test_a_create_naming_a_type_outside_the_declared_list_is_refused_and_writes_no_file(tmp_path: Path) -> None:
    path, built = typed(tmp_path, TYPES)
    assert built.create is not None

    written = built.create("New", {"type": "epic"})

    assert not written.ok and "spike, story" in written.output
    assert list(native_root(tmp_path).glob("tasks/*.md")) == [path]
    assert built.create("New", {"type": "story"}).ok


def test_a_write_that_leaves_an_undeclared_type_alone_still_lands(tmp_path: Path) -> None:
    _, built = typed(tmp_path, TYPES, type="epic")
    assert built.edit is not None and built.writer is not None

    assert built.writer("task-1", "Done", "operator").ok
    assert built.edit("task-1", {"title": "Renamed"}, "").ok


def test_a_create_naming_no_type_lands_when_a_list_is_declared(tmp_path: Path) -> None:
    _, built = typed(tmp_path, TYPES)
    assert built.create is not None

    assert built.create("New", {}).ok


@pytest.mark.parametrize("name", ["epic", "Anything Goes"])
def test_any_type_lands_when_no_list_is_declared(tmp_path: Path, name: str) -> None:
    path, built = typed(tmp_path, None)
    assert built.edit is not None

    assert built.edit("task-1", {"type": name}, "").ok
    assert f"type: {name}\n" in path.read_text()
