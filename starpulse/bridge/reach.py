"""Which held tasks an incident type reaches, from `[bridge.incidents.<type>]`.

A task is in reach when it is in the working lane, the only one a task can wait from, and matches every selector the type
declares: any one of its `kinds` (`kind-*` labels) and any one of its `areas` (`area-*` labels).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Reach:
    kinds: tuple[str, ...] = ()
    areas: tuple[str, ...] = ()

    def covers(self, agent: dict[str, Any], working: str) -> bool:
        labels = set(agent.get("labels", ()))
        return (
            agent["state"] == working
            and (not self.kinds or any(f"kind-{kind}" in labels for kind in self.kinds))
            and (not self.areas or any(f"area-{area}" in labels for area in self.areas))
        )


def parse_reach(table: dict[str, Any]) -> dict[str, Reach]:
    """The reach of each incident type; a type that declares no selector raises `ValueError`, since it would reach every
    session."""
    reach = {kind: Reach(*(tuple(selectors.get(name, ())) for name in ("kinds", "areas"))) for kind, selectors in table.items()}
    for kind, found in reach.items():
        if not (found.kinds or found.areas):
            raise ValueError(f"incidents.{kind} declares no kinds or areas, so it would reach every session")
    return reach
