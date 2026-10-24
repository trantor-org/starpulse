"""A skill machine's declared `next` edge is served as its skill's next; a machine declaring none serves null."""

from __future__ import annotations

from pathlib import Path

import pytest

from starpulse._internal.board.project_machines import draw
from starpulse._internal.machines.machine_definition import load_machine

FIXTURE = Path(__file__).parents[2] / "fixtures" / "machines" / "authoring-skills.yaml"


def _drawn(tmp_path: Path, extra: str) -> dict:
    path = tmp_path / "deliver.yaml"
    path.write_text(FIXTURE.read_text() + extra)
    return draw({"deliver": load_machine(path)}, lambda dag: dag, ())["deliver"]


def test_a_machine_declaring_next_serves_it_as_the_skill_next_edge(tmp_path: Path) -> None:
    assert _drawn(tmp_path, "next:\n  kind: skill\n  name: review-fix\n")["next"] == {"kind": "skill", "name": "review-fix"}


def test_an_operation_next_edge_is_served_with_its_kind(tmp_path: Path) -> None:
    assert _drawn(tmp_path, "next:\n  kind: operation\n  name: merge\n")["next"] == {"kind": "operation", "name": "merge"}


def test_a_machine_declaring_no_next_serves_null(tmp_path: Path) -> None:
    assert _drawn(tmp_path, "")["next"] is None


def test_a_next_of_an_unknown_kind_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _drawn(tmp_path, "next:\n  kind: nowhere\n  name: x\n")
