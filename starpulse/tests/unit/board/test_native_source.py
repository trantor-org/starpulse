"""A task's `source` front matter key, the idempotency key a scheduled caller stores: create and edit set it, an empty edit removes it."""

from pathlib import Path
from typing import Any

from starpulse.board.adapters.native import board
from starpulse.board.adapters.upstream_backlog import _split


def _front(base: Path, task: str) -> dict[str, Any]:
    [path] = (base / ".starpulse" / "board" / "tasks").glob(f"{task.lower()}*.md")
    return _split(path.read_text())[0]


def test_a_create_with_a_source_writes_it_to_the_front_matter(tmp_path: Path) -> None:
    built = board({}, tmp_path)

    task = built.create("Draw the board", {"source": "scheduled:caller-a:0f7625"}).output

    assert _front(tmp_path, task)["source"] == "scheduled:caller-a:0f7625"


def test_an_edit_sets_the_source_and_an_empty_edit_removes_it(tmp_path: Path) -> None:
    built = board({}, tmp_path)
    task = built.create("Draw the board", {}).output

    assert built.edit(task, {"source": "scheduled:caller-a:0f7625"}, "").ok
    assert _front(tmp_path, task)["source"] == "scheduled:caller-a:0f7625"

    assert built.edit(task, {"source": ""}, "").ok
    assert "source" not in _front(tmp_path, task)


def test_a_source_that_is_not_text_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    built = board({}, tmp_path)
    task = built.create("Draw the board", {}).output
    before = _front(tmp_path, task)

    assert not built.edit(task, {"source": ["a"]}, "").ok
    assert _front(tmp_path, task) == before
