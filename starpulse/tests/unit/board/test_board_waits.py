"""A board adapter hands the server the facts its machine's states wait on, and the lane each wait's event reaches."""

from pathlib import Path

from starpulse.board.adapters import native
from starpulse.pulls.task_actor import moves_of

MACHINE = """\
name: board
states:
  to_do: {initial: true}
  in_progress: {waits: {deps_done: DEPS_DONE}}
  done: {final: true}
events:
  CLAIM: [{from: to_do, to: in_progress}]
  DEPS_DONE: [{from: in_progress, to: done}]
"""


def test_a_native_board_with_a_machine_file_carries_the_machines_waits(tmp_path: Path) -> None:
    (tmp_path / "board.yaml").write_text(MACHINE)

    built = native.board({"machine": "board.yaml"}, tmp_path)

    assert built.waits == {"in_progress": {"deps_done": "DEPS_DONE"}}
    assert moves_of(built.machines(lambda name: name, [])["board"]) == {
        ("to_do", "CLAIM"): "in_progress",
        ("in_progress", "DEPS_DONE"): "done",
    }


def test_a_board_without_a_machine_file_waits_on_nothing(tmp_path: Path) -> None:
    assert native.board({}, tmp_path).waits == {}
