"""The machines the package's own tests draw: a Board from a project's statuses, and two lifecycle flows."""

from pathlib import Path

from starpulse._internal.machines.machine_definition import load_machine
from starpulse._internal.machines.snapshot import describe
from starpulse._internal.machines.state_roles import StateRoles
from starpulse._internal.machines.transitions import board_machine

FIXTURES = Path(__file__).parent / "fixtures" / "machines"
#: The Board's statuses, in the order its lanes are drawn.
STATUSES = ("To Do", "Ready", "In Progress", "Review", "Done")


def flow(name: str) -> dict:
    """The fixture machine `<name>.yaml` as the page draws it."""
    return describe(load_machine(FIXTURES / f"{name}.yaml").machine)


MACHINES = {
    "board": board_machine(STATUSES),
    "in-progress": flow("in-progress"),
    "authoring-skills": flow("authoring-skills"),
}
FLOWS = tuple(MACHINES)
#: The roles of a board whose States are `ready`, `waiting`, `in_progress`, `review`, `needs_attention` and `done`.
ROLES = StateRoles(
    {
        "ready": "waiting_on_fact",
        "waiting": "waiting_on_fact",
        "in_progress": "resting",
        "review": "waiting_on_fact",
        "needs_attention": "waiting_on_person",
        "done": "final",
    },
    {"ready": {"criteria_unmet": ""}, "waiting": {"criteria_met": ""}, "review": {"pr_terminal": ""}},
)
