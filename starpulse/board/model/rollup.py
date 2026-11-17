"""A pull request's checks status, derived from the required checks of its current head: what the board reads everywhere."""

from collections.abc import Mapping, Sequence
from typing import Any


def checks_verdict(
    state: str, checks: str, head: str, rollup: Mapping[str, Any] | None, required: Sequence[Mapping[str, Any]]
) -> str:
    """The one checks status of a pull request: as stored once it is merged or closed; while open, the state of the
    `pr-checks` rollup `{sha, state}` of its current head (`passed` is `pass`), and `pending` with one of another
    head. The rollup counts every required check and commit status of that head alone, so a failure of an earlier
    head or of a check not required never moves it, and a required check not yet posted keeps it pending.
    A record no rollup ever reached (`rollup` None) reads its stored `required` checks instead: `failing` if any
    failed, `pass` if there are some and all passed, else `pending`; a rollup, even of another head, outvotes them."""
    if state != "OPEN":
        return checks
    if not head:
        return "pending"
    if rollup is None:
        results = {check["result"] for check in required}
        return "failing" if "failing" in results else "pass" if results == {"pass"} else "pending"
    if rollup.get("sha") != head:
        return "pending"
    return {"passed": "pass", "failing": "failing"}.get(str(rollup.get("state")), "pending")
