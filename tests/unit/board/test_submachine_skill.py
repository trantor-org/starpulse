"""A submachine link names the skill its inner machine runs; the page reads it from the drawn link."""

from __future__ import annotations

from pathlib import Path

import pytest
from starpulse.board.adapters.project_machines import draw
from starpulse.contracts.api.dto.machine import Machine
from starpulse.machine_engine.adapters.machine_loader import load_machine

PARENT = """name: Parent
states:
  work: {initial: true}
  done: {final: true}
events:
  WORK_DONE:
    - {from: work, to: done}
submachines:
  - {state: work, machine: child, exits: {finished: WORK_DONE}%s}
"""
CHILD = """name: Child
states:
  start: {initial: true}
  finished: {final: true}
events:
  FINISH:
    - {from: start, to: finished}
"""


def _link(tmp_path: Path, extra: str) -> dict:
    (tmp_path / "parent.yaml").write_text(PARENT % extra)
    (tmp_path / "child.yaml").write_text(CHILD)
    flows = {name: load_machine(tmp_path / f"{name}.yaml") for name in ("parent", "child")}
    return draw(flows, lambda dag: dag, ())["parent"]["submachines"][0]


def test_a_link_declaring_a_skill_draws_it(tmp_path: Path) -> None:
    assert _link(tmp_path, ", skill: review-fix")["skill"] == "review-fix"


def test_a_link_declaring_no_skill_draws_an_empty_one(tmp_path: Path) -> None:
    assert _link(tmp_path, "")["skill"] == ""


@pytest.mark.parametrize("extra", ["", ", skill: tdd"])
def test_the_api_submachine_model_serves_the_drawn_skill(tmp_path: Path, extra: str) -> None:
    drawn = _link(tmp_path, extra)
    assert Machine.model_json_schema()  # the model builds
    from starpulse.contracts.api.dto.machine import Submachine

    assert Submachine.model_validate(drawn).model_dump()["skill"] == drawn["skill"]
