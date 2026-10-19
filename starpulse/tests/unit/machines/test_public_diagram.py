"""`starpulse.diagram`: the DOT the server draws for each machine of a project, without a server."""

import shutil
from pathlib import Path

from starpulse._internal.board import machines_only
from starpulse._internal.machines.diagram import dot
from starpulse.diagram import machine_dot

FIXTURES = Path(__file__).parents[2] / "fixtures" / "machines"


def test_dot_equals_what_the_server_draws_for_each_machine(tmp_path: Path) -> None:
    directory = tmp_path / ".starpulse" / "machines"
    directory.mkdir(parents=True)
    for name in ("in-progress.yaml", "authoring-skills.yaml"):
        shutil.copy(FIXTURES / name, directory / name)
    drawn = machines_only.board({"type": "machines"}, tmp_path).machines(lambda state: state, ())

    assert machine_dot(tmp_path) == {name: dot(name, machine) for name, machine in drawn.items()}
    assert machine_dot(tmp_path)
