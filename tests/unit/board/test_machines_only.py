"""The `machines` board type: a project's declared machines, drawn as the native board draws them, with no task source."""

from pathlib import Path
from typing import Any

import pytest
from starpulse.board.adapters.machines_only import board
from starpulse.board.model.adapter_types import module_name

BOARD = """\
name: Board
states:
  to_do: {initial: true}
  done: {final: true}
events:
  to_done: [{from: to_do, to: done}]
"""
DELIVERY = """\
name: Delivery
states:
  start: {initial: true}
  shipped: {final: true}
events:
  SHIP: [{from: start, to: shipped}]
"""


def declare(base: Path, **files: str) -> None:
    machines = base / ".starpulse" / "machines"
    machines.mkdir(parents=True)
    for stem, text in files.items():
        (machines / f"{stem.replace('_', '-')}.yaml").write_text(text)


def test_every_machine_file_is_drawn_under_its_file_stem_with_no_board_directory(tmp_path: Path) -> None:
    declare(tmp_path, board=BOARD, in_progress=DELIVERY)

    machines = board({"type": "machines"}, tmp_path).machines(lambda name: f"dagu/{name}", ())

    assert list(machines) == ["board", "in-progress"]
    assert [state["id"] for state in machines["board"]["states"]] == ["to_do", "done"]
    assert not (tmp_path / ".starpulse" / "board").exists()


def test_a_project_with_no_machines_draws_none(tmp_path: Path) -> None:
    assert board({"type": "machines"}, tmp_path).machines(lambda name: name, ()) == {}


def test_it_follows_no_task_source_because_instances_forward_their_events(tmp_path: Path) -> None:
    declared = board({"type": "machines"}, tmp_path)
    feed: Any = object()
    log: Any = object()

    assert declared.start(feed, "group", log) is None
    assert declared.writer is None


def test_it_takes_no_settings_beyond_its_type(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="board type machines takes no settings: a, path"):
        board({"type": "machines", "path": "x", "a": 1}, tmp_path)


def test_the_bare_type_machines_resolves_to_this_module() -> None:
    assert module_name("machines") == "starpulse.board.adapters.machines_only"
