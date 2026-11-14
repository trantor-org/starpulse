"""Whether a pull request's required checks all passed for its current head, as the board judges it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def checks_verdict(state: str, checks: str, head: str, rollup: Mapping[str, Any] | None) -> str:
    """The checks verdict the board reads of a pull request: as stored once it is merged or closed; while open,
    `failing` or `pending` as stored, else `pass` only when the `pr-checks` rollup `{sha, state}` of the head says
    `passed`. No rollup, one of another head or one not passed is `pending`.

    The stored `checks` come from the required checks GitHub has posted, so a check not yet posted leaves them `none`
    and reads as green: only the rollup counts the required checks that never posted."""
    if state != "OPEN" or checks in ("failing", "pending"):
        return checks
    rolled = rollup or {}
    return "pass" if head and rolled.get("sha") == head and rolled.get("state") == "passed" else "pending"
