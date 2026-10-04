"""The machines the package's own tests draw: a Board from a project's statuses, and two lifecycle flows."""

from pathlib import Path

from starpulse.machine_definition import load_machine
from starpulse.snapshot import describe
from starpulse.upstream_backlog import board_machine

FIXTURES = Path(__file__).parent / "fixtures" / "machines"
#: The Board's statuses, in the order its lanes are drawn.
STATUSES = ("To Do", "Ready", "In Progress", "Review", "Done")


def flow(name: str) -> dict:
    """The fixture machine `<name>.yaml` as the page draws it."""
    return describe(load_machine(FIXTURES / f"{name}.yaml").machine, name)


MACHINES = {
    "board": board_machine(STATUSES),
    "in-progress": flow("in-progress"),
    "authoring-skills": flow("authoring-skills"),
}
FLOWS = tuple(MACHINES)
