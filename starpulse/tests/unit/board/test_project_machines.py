"""A board's machines: the Board file `machine` names, and every other file under the project's `.starpulse/machines/`."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from starpulse._internal.board.native import board
from starpulse._internal.machines.machine_definition import MachineDefinitionError

BOARD = """\
name: Board
states:
  to_do: {initial: true}
  in_progress: {}
  done: {final: true}
events:
  to_in_progress: [{from: to_do, to: in_progress}]
  to_done: [{from: in_progress, to: done}]
"""
DELIVERY = """\
name: Delivery
states:
  start: {initial: true}
  shipped: {final: true}
events:
  SHIP: [{from: start, to: shipped}]
"""


def project(base: Path, workflows: tuple[str, ...] = (), **files: str) -> dict[str, dict]:
    """The machines of a native board whose `.starpulse/machines/` holds `files` (named by stem), the Board among them."""
    machines = base / ".starpulse" / "machines"
    machines.mkdir(parents=True)
    for stem, text in files.items():
        (machines / f"{stem.replace('_', '-')}.yaml").write_text(text)
    config = base / ".starpulse" / "board" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(yaml.safe_dump({"project_name": "demo", "statuses": ["To Do", "In Progress", "Done"]}))
    return board({"machine": ".starpulse/machines/board.yaml"}, base).machines(lambda name: f"dagu/{name}", workflows)


def test_every_machine_file_beside_the_board_is_drawn_under_its_file_stem(tmp_path: Path) -> None:
    machines = project(tmp_path, board=BOARD, in_progress=DELIVERY)

    assert list(machines) == ["board", "in-progress"]
    assert [state["id"] for state in machines["in-progress"]["states"]] == ["start", "shipped"]


def test_the_board_file_draws_its_tiers_main_line_and_rests(tmp_path: Path) -> None:
    declared = (
        BOARD + "tiers: [[to_do], [in_progress], [done]]\nmain_line: [to_do, in_progress, done]\nrests: [in_progress]\n"
    )

    body = project(tmp_path, board=declared)["board"]

    assert body["tiers"] == [["to_do"], ["in_progress"], ["done"]]
    assert body["mainLine"] == ["to_do", "in_progress", "done"]
    assert {state["id"]: state["final"] for state in body["states"]} == {
        "to_do": False,
        "in_progress": True,
        "done": True,
    }


def test_a_state_that_opens_a_sibling_machine_draws_the_link_with_the_event_each_exit_fires(tmp_path: Path) -> None:
    declared = (
        BOARD
        + "subflows:\n  - {state: in_progress, flow: in-progress, exits: {shipped: to_done}, when: a PR is open}\n"
    )

    machines = project(tmp_path, board=declared, in_progress=DELIVERY)

    assert machines["board"]["subflows"] == [
        {
            "state": "in_progress",
            "flow": "in-progress",
            "exits": {"shipped": "to_done"},
            "parent": "board",
            "when": "a PR is open",
        }
    ]
    assert "subflows" not in machines["in-progress"]


def test_a_launching_workflow_is_drawn_as_the_page_names_it_beside_the_flow_it_starts(tmp_path: Path) -> None:
    declared = BOARD + "launches:\n  nightly: {skill: shipping, flow: in-progress}\n  weekly: {skill: auditing}\n"

    launches = project(tmp_path, board=declared, in_progress=DELIVERY)["board"]["launches"]

    assert launches == {
        "dagu/nightly": {"skill": "shipping", "flow": "in-progress"},
        "dagu/weekly": {"skill": "auditing", "flow": None},
    }


def test_the_board_draws_every_writer_and_which_actors_are_workflows(tmp_path: Path) -> None:
    declared = (
        BOARD + "writers:\n  to_done: [{actor: dagu/merge, trigger: main}, {actor: agent, trigger: board_task}]\n"
    )

    body = project(tmp_path, workflows=("dagu/merge",), board=declared)["board"]

    assert body["writers"] == {
        "to_done": [{"actor": "dagu/merge", "trigger": "main"}, {"actor": "agent", "trigger": "board_task"}]
    }
    assert body["dagActors"] == ["dagu/merge"]


def test_a_machine_whose_writers_name_an_unlisted_workflow_is_refused_by_name(tmp_path: Path) -> None:
    writers = "writers:\n  SHIP: [{actor: dagu/ghost, trigger: x}]\n"

    with pytest.raises(MachineDefinitionError, match=r"in-progress: writers name workflows .*\['dagu/ghost'\]"):
        project(tmp_path, workflows=("dagu/merge",), board=BOARD, in_progress=DELIVERY + writers)


@pytest.mark.parametrize(
    ("declared", "named"),
    [
        ("tiers: [[to_do, nowhere]]\n", "tiers.*nowhere"),
        ("rests: [nowhere]\n", "rests.*nowhere"),
        ("subflows: [{state: in_progress, flow: absent, exits: {}}]\n", "absent"),
        ("subflows: [{state: nowhere, flow: in-progress, exits: {}}]\n", "nowhere"),
        ("subflows: [{state: in_progress, flow: in-progress, exits: {shipped: NOPE}}]\n", "NOPE"),
        ("launches: {nightly: {skill: s, flow: absent}}\n", "absent"),
    ],
)
def test_a_declaration_naming_a_state_event_or_flow_that_does_not_exist_is_refused(
    tmp_path: Path, declared: str, named: str
) -> None:
    with pytest.raises(ValueError, match=named):
        project(tmp_path, board=BOARD + declared, in_progress=DELIVERY)


def test_a_machine_another_opens_with_flow_is_a_child_not_a_flow_of_its_own(tmp_path: Path) -> None:
    parent = BOARD.replace("in_progress: {}", "in_progress: {flow: delivery.yaml}")

    assert list(project(tmp_path, board=parent, delivery=DELIVERY)) == ["board"]


def test_loading_the_machines_leaves_board_client_unimported(tmp_path: Path) -> None:
    project(tmp_path, board=BOARD, in_progress=DELIVERY)
    code = (
        "import sys\nfrom pathlib import Path\nimport starpulse.board\n"
        f"built = starpulse.board.load('native', {{'machine': '.starpulse/machines/board.yaml'}}, Path({str(tmp_path)!r}))\n"
        "built.machines(lambda name: name, ())\n"
        "print(sorted(name for name in sys.modules if name.split('.')[0] == 'board_client'))\n"
    )

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert done.stdout.strip() == "[]"
