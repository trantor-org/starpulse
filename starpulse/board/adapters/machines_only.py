"""The `machines` board: a project's declared machines, with no task source.

It draws every file under `.starpulse/machines/` as the native board draws them, the Board machine among them, and
places no task: it reads no board directory, finds no task and refuses every write.
"""

from collections.abc import Collection, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starpulse.board.adapters import project_machines
from starpulse.board.model.seam import Board, Written
from starpulse.machine_engine.model.state_roles import StateRoles
from starpulse.machine_engine.model.transitions import DEFAULT_STATUSES

if TYPE_CHECKING:
    from starpulse.machine_engine.model.snapshot import Qualify


def _nothing(*_: Any) -> None:
    """Nothing to follow, tell or sweep: the tasks arrive as lane entries."""


def _refused(*_: Any, **__: Any) -> Written:
    return Written(False, "the machines board holds no tasks", unavailable=True)


def _absent(*_: Any) -> None:
    return None


def refusing(**fields: Any) -> Board:
    """A Board that holds no tasks: every write refuses and every read finds nothing; `fields` replace its parts."""
    return Board(**{
        "machines": lambda qualify, workflows: {},
        "start": _nothing,
        "keys": None,
        "cues": lambda _qualify: (),
        "waits": {},
        "roles": StateRoles.of_statuses(DEFAULT_STATUSES),
        "writer": _refused,
        "assign": _refused,
        "release": _refused,
        "source": "the events instances forward",
        "read": _absent,
        "read_archived": _absent,
        "edit": _refused,
        "archive": _refused,
        "restore": _refused,
        "standing": _absent,
        "readable": lambda *_: "",
        "complete": _refused,
        "reopen": _refused,
        "retire": _refused,
        "retired": lambda *_: (),
        "retired_projected": lambda *_: [],
        "retired_page": lambda *_: ([], None),
        "import_retired": _refused,
        "reconcile": lambda *_: False,
        "files": lambda: (),
        "done_files": lambda: (),
        "rescan": lambda: 0,
        "create": _refused,
        "milestones": lambda: [],
        "read_milestone": _absent,
        "create_milestone": _refused,
        "edit_milestone": _refused,
        "archive_milestone": _refused,
        "read_doc": _absent,
        "create_doc": _refused,
        "edit_doc": _refused,
        "archive_doc": _refused,
        "restore_doc": _refused,
        "holds": lambda *_: (),
        "unfinished": lambda *_: (),
        "parked": _nothing,
        "released": _nothing,
        "idle": None,
        "returned": _nothing,
        "alive": lambda *_: False,
        "enqueued": _nothing,
        "verifying": _nothing,
        "closed": _nothing,
        "entered": _nothing,
        "attach": _nothing,
        **fields,
    })


def board(settings: Mapping[str, Any], base: Path) -> Board:
    """The machines under `base`'s `.starpulse/machines/`; it takes no settings beyond its `type`."""
    if unknown := sorted(settings.keys() - {"type"}):
        raise ValueError(f"board type machines takes no settings: {', '.join(unknown)}")

    def machines(qualify: Qualify, workflows: Collection[str]) -> dict[str, dict]:
        return project_machines.draw(project_machines.load(base, None), qualify, workflows)

    return refusing(machines=machines)
