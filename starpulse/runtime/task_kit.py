"""The task builder the kit's tests seed a board with, which `adapter_kit` exports."""

from starpulse.contracts.adapters import BoardTask


def task(task_id: str, status: str = "To Do", **fields) -> BoardTask:
    """A task in the lane `status` names, its title derived from its key and its team `demo` unless given."""
    return BoardTask(
        id=task_id,
        title=fields.pop("title", f"Title of {task_id}"),
        team=fields.pop("team", "demo"),
        lane=status.lower().replace(" ", "_"),
        **fields,
    )
