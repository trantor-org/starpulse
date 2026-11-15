"""The tiers a Board task takes. It imports no model library, so a board load reads them without `pydantic`;
`starpulse.contracts.adapters` re-exports them beside `BoardTask`."""

from collections.abc import Iterable
from typing import Literal, get_args

#: A task's tier, highest first: the one field that says how soon the scheduler admits it among Ready tasks.
Tier = Literal["regression", "bug", "leverage", "standard", "decide"]
TIERS: tuple[str, ...] = get_args(Tier)
#: The tier of a task that names none.
DEFAULT_TIER: Tier = "standard"
#: The tiers that take only the room every other tier leaves, and rank after them whatever their position.
LEFTOVER_TIERS: frozenset[str] = frozenset({"decide"})


def implied_tier(task_type: str, labels: Iterable[str]) -> Tier:
    """The tier a task that names none takes from its type and labels: a `regression` label, then `kind-decide`, then
    `type: bug`, else `DEFAULT_TIER` (ADR "The Autopilot Admits Ready Tasks by Their Tier Field")."""
    labels = set(labels)
    if "regression" in labels:
        return "regression"
    if "kind-decide" in labels:
        return "decide"
    return "bug" if task_type.strip().lower() == "bug" else DEFAULT_TIER
