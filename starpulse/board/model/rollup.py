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
    A record no rollup ever reached (`rollup` None) is `failing` if a stored `required` check failed, else `pending`:
    the stored checks never name the base's required set, so only a rollup says `pass`; a rollup, even of another head,
    outvotes them."""
    if state != "OPEN":
        return checks
    if not head:
        return "pending"
    if rollup is None:
        return "failing" if any(check["result"] == "failing" for check in required) else "pending"
    if rollup.get("sha") != head:
        return "pending"
    return {"passed": "pass", "failing": "failing"}.get(str(rollup.get("state")), "pending")
