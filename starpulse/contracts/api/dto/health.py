"""The history a task carries."""

from pydantic import Field

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.pages import MachineStep


class MachineHistory(_Api):
    """`GET /api/history?task=&machine=`: a task's path on one machine, and how many steps it has taken."""

    task: str
    machine: str
    path: list[MachineStep]
    steps: int


class MachineEvent(_Api):
    at: float
    machine: str
    event: str
    # `from` is a Python keyword.
    origin: str = Field(alias="from")
    to: str


class TaskEventHistory(_Api):
    """`GET /api/history?task=&hours=`: every machine event of a task in the window, oldest first."""

    task: str
    hours: float
    events: list[MachineEvent]


# A typed dict, not a model: a window lists thousands of stuck tasks and a model instance each costs more than the
# rest of the read. Its schema is the model's (a comment, not a docstring, so the generated types do not change).
