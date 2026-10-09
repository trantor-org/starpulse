"""The CI machine: a pull request's pushes, check results, re-runs, conflicts and merges, as GitHub moves them.

StarPulse ships this one machine and only observes it: `machines/ci.yaml` declares `source: GitHub`, so the page
draws it apart from a machine StarPulse's own actors move. The config's `[ci]` table attaches it to Board states.
"""

from collections.abc import Collection, Mapping
from pathlib import Path

from starpulse._internal.machines.machine_definition import load_machine
from starpulse._internal.machines.snapshot import describe
from starpulse._internal.config.config import ConfigError

CI = load_machine(Path(__file__).parents[2] / "machines" / "ci.yaml")
#: The machine as the page draws it, keyed by name like a board adapter's machines.
CI_MACHINES = {CI.name: describe(CI.machine)}

#: What has to hold for the CI machine to run under a Board state.
WHEN = "a PR is open"


def attach(machines: Mapping[str, dict], states: Collection[str]) -> dict[str, dict]:
    """`machines` with the CI machine added and a sub-flow link to it under each of the Board's `states`.

    A state the Board machine lacks is a `ConfigError` naming it; the Board machine passed in is left as it was.
    """
    board = machines["board"]
    known = {state["id"] for state in board["states"]}
    if missing := [state for state in states if state not in known]:
        raise ConfigError(
            f"ci: {', '.join(missing)} is not a state of the board machine; it has {', '.join(sorted(known))}"
        )
    links = [{"state": state, "flow": CI.name, "exits": {}, "parent": "board", "when": WHEN} for state in states]
    return {**machines, "board": {**board, "subflows": [*board.get("subflows", []), *links]}, **CI_MACHINES}
