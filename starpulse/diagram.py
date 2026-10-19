"""The DOT a project's machines draw as, `machine_dot(base)`; the implementation is in `starpulse._internal`."""

from pathlib import Path

__all__ = ["machine_dot"]


def machine_dot(base: Path) -> dict[str, str]:
    """Graphviz DOT for each machine under `base`'s `.starpulse/machines/`, by name, as `machine show --format dot` prints it."""
    from starpulse._internal.board import project_machines  # noqa: PLC0415 - import cost, paid on first use
    from starpulse._internal.machines.diagram import dot  # noqa: PLC0415 - import cost, paid on first use

    drawn = project_machines.draw(project_machines.load(base, None), lambda state: state, ())
    return {name: dot(name, machine) for name, machine in drawn.items()}
