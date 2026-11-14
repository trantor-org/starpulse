"""A pull request's checks status, derived from the required checks of its current head: what the board reads everywhere."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def checks_verdict(state: str, checks: str, head: str, rollup: Mapping[str, Any] | None) -> str:
    """The one checks status of a pull request: as stored once it is merged or closed; while open, the state of the
    `pr-checks` rollup `{sha, state}` of its current head (`passed` is `pass`), and `pending` with no rollup or one
    of another head. The rollup counts every required check and commit status of that head alone, so a failure of an
    earlier head or of a check not required never moves it, and a required check not yet posted keeps it pending."""
    if state != "OPEN":
        return checks
    rolled = rollup or {}
    if not head or rolled.get("sha") != head:
        return "pending"
    return {"passed": "pass", "failing": "failing"}.get(str(rolled.get("state")), "pending")
