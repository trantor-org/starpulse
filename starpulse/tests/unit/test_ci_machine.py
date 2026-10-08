"""The CI machine StarPulse ships: a pull request's pushes, checks, re-runs, conflicts and merges, moved by GitHub."""

import pytest

from starpulse.projections.ci import CI, CI_MACHINES

#: Every row of the approved transition table (starpulse PR 96), one per source state: (from, event, to).
TABLE = [
    ("opened", "PUSHED", "running"),
    ("running", "CHECKS_PASSED", "passing"),
    ("running", "CHECKS_FAILED", "failing"),
    ("failing", "PUSHED", "running"),
    ("failing", "RERUN", "running"),
    ("passing", "PUSHED", "running"),
    ("passing", "CONFLICTED", "conflicting"),
    ("failing", "CONFLICTED", "conflicting"),
    ("conflicting", "REBASED", "running"),
    ("passing", "MERGED", "merged"),
    ("merged", "PR_OPENED", "opened"),
]


@pytest.mark.parametrize(("source", "event", "target"), TABLE, ids=[f"{s}-{e}" for s, e, _ in TABLE])
def test_each_row_of_the_table_moves_the_machine_from_its_state_to_its_target(
    source: str, event: str, target: str
) -> None:
    machine = CI.machine(start_value=source)

    machine.send(event)

    assert machine.configuration_values == {target}


def test_the_machine_has_no_transition_the_table_does_not_list() -> None:
    drawn = {(t["source"], t["event"], t["target"]) for t in CI_MACHINES["ci"]["transitions"]}

    assert drawn == set(TABLE)


def test_a_merged_pull_request_is_not_final_so_a_task_with_a_second_one_reopens() -> None:
    states = {s["id"]: s for s in CI_MACHINES["ci"]["states"]}

    assert [s for s, state in states.items() if state["final"]] == []
    assert [s for s, state in states.items() if state["initial"]] == ["opened"]
    assert list(states) == ["opened", "running", "passing", "failing", "conflicting", "merged"]


def test_github_moves_it() -> None:
    assert CI_MACHINES["ci"]["source"] == "GitHub"
