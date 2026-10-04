"""Board tasks built the way a board adapter places them."""

from starpulse.contracts import BoardTask


def task(task_id: str, status: str = "To Do", **fields) -> BoardTask:
    """A task in the lane `status` names, its title derived from its key unless given."""
    return BoardTask(
        id=task_id,
        title=fields.pop("title", f"Title of {task_id}"),
        lane=status.lower().replace(" ", "_"),
        **fields,
    )
