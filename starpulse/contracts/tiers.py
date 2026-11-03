"""The tiers a Board task takes. It imports no model library, so a board load reads them without `pydantic`;
`starpulse.contracts.adapters` re-exports them beside `BoardTask`."""

from typing import Literal, get_args

#: A task's tier, highest first: the one field that says how soon the scheduler admits it among Ready tasks.
Tier = Literal["regression", "bug", "leverage", "standard", "decide"]
TIERS: tuple[str, ...] = get_args(Tier)
#: The tier of a task that names none.
DEFAULT_TIER: Tier = "standard"
